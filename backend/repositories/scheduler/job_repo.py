"""Scheduler job DB 仓库 (Postgres + SQLAlchemy).

替代 :mod:`backend.api.scheduler` 里:
  - ``_load_jobs_registry()``    → :meth:`SchedulerJobRepository.list_jobs`
  - ``JOB_CATEGORY_MAP`` dict     → :meth:`SchedulerJobRepository.list_categories_with_counts`
  - ``_categories_for(job_id)``  → :meth:`SchedulerJobRepository.category_ids_for_job`

约定 (跟 CLAUDE.md / 项目分层一致):
  - repository 不做 commit: 事务边界 = ``session_scope()``
  - repository 不做 HTTP / jsonify / 业务校验: 那层在 API
  - repository 不 import backend.api.*
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from backend.models.scheduler import (
    SchedulerJob,
    SchedulerJobCategory,
    SchedulerJobCategoryMapping,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 序列化 helpers
# ---------------------------------------------------------------------------

def _job_to_dict(
    job: SchedulerJob,
    *,
    category_ids: list[int] | None = None,
) -> dict[str, Any]:
    """把 ORM 行转成 ``/api/scheduler/jobs`` 返回的 item 形态.

    前端依赖的字段: id / name / description / config_file / service_module / service_class /
    registered_at / enabled. 其它 (supports_enable / config_enabled / config / live / last_run /
    categories) 在 API 层再叠加.

    这里 ``id`` 复用 ``code`` (前端 ``job.id`` = ``turnover_refresh`` 字符串), 不暴露 uuid.
    """
    out: dict[str, Any] = {
        "id": job.code,
        "name": job.name,
        "description": job.description,
        "config_file": job.config_file or "",
        "service_module": job.service_module,
        "service_class": job.service_class,
        "registered_at": job.registered_at.isoformat() if job.registered_at else None,
        "enabled": bool(job.is_enabled),
    }
    if category_ids is not None:
        out["_category_ids"] = category_ids
    return out


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class SchedulerJobRepository:
    """Scheduler job + category 多对多映射的 DB CRUD. 一个实例绑一个 Session, 一次性用."""

    def __init__(self, db: Session):
        self.db = db

    # ---- categories (读) ----

    def _active_categories_sorted(self) -> list[SchedulerJobCategory]:
        return list(
            self.db.execute(
                select(SchedulerJobCategory)
                .where(
                    SchedulerJobCategory.deleted_at.is_(None),
                    SchedulerJobCategory.status == "active",
                )
                .order_by(
                    SchedulerJobCategory.sort_order.asc(),
                    SchedulerJobCategory.created_at.asc(),
                )
            )
            .scalars()
            .all()
        )

    def _category_uuid_to_int_id(self) -> dict[UUID, int]:
        """category uuid → 1..N 连续 int (按 sort_order 升序). 前端用 int 当 category id."""
        return {
            c.id: idx
            for idx, c in enumerate(self._active_categories_sorted(), start=1)
        }

    def list_categories_with_counts(self) -> list[dict[str, Any]]:
        """列出所有 active category + 每类下的 alive job 数.

        跟 ``/api/scheduler/categories`` 响应形态一致:
          {id: int, label, icon_hint, sort_order, description, count}
        """
        cats = self._active_categories_sorted()
        if not cats:
            return []

        cat_uuid_to_count: dict[UUID, int] = dict(
            self.db.execute(
                select(
                    SchedulerJobCategoryMapping.category_id,
                    func.count(SchedulerJobCategoryMapping.job_id),
                )
                .join(SchedulerJob, SchedulerJob.id == SchedulerJobCategoryMapping.job_id)
                .where(
                    SchedulerJobCategoryMapping.deleted_at.is_(None),
                    SchedulerJob.deleted_at.is_(None),
                )
                .group_by(SchedulerJobCategoryMapping.category_id)
            ).all()
        )

        items: list[dict[str, Any]] = []
        for idx, c in enumerate(cats, start=1):
            items.append(
                {
                    "id": idx,
                    "label": c.label,
                    "icon_hint": c.icon_hint or "",
                    "sort_order": c.sort_order,
                    "description": c.description or "",
                    "count": int(cat_uuid_to_count.get(c.id, 0)),
                }
            )
        return items

    # ---- jobs (读) ----

    def list_jobs(self) -> list[dict[str, Any]]:
        """列出所有 alive 的 job + 每 job 的 category_id 列表.

        排序: 按 name 升序, 同 name 按 registered_at 升序.
        """
        jobs = list(
            self.db.execute(
                select(SchedulerJob)
                .where(SchedulerJob.deleted_at.is_(None))
                .order_by(
                    SchedulerJob.name.asc(),
                    SchedulerJob.registered_at.asc().nulls_last(),
                )
            )
            .scalars()
            .all()
        )
        if not jobs:
            return []

        cat_uuid_to_int = self._category_uuid_to_int_id()

        # 一次拉所有 alive mapping
        mappings = self.db.execute(
            select(
                SchedulerJobCategoryMapping.job_id,
                SchedulerJobCategoryMapping.category_id,
            ).where(SchedulerJobCategoryMapping.deleted_at.is_(None))
        ).all()
        job_to_cat_uuids: dict[UUID, list[UUID]] = {}
        for job_id, cat_uuid in mappings:
            job_to_cat_uuids.setdefault(job_id, []).append(cat_uuid)

        out: list[dict[str, Any]] = []
        for j in jobs:
            cat_int_ids = sorted(
                cat_uuid_to_int[cu]
                for cu in job_to_cat_uuids.get(j.id, [])
                if cu in cat_uuid_to_int
            )
            out.append(_job_to_dict(j, category_ids=cat_int_ids))
        return out

    def get_job_by_code(self, code: str) -> dict[str, Any] | None:
        job = self.db.execute(
            select(SchedulerJob)
            .where(SchedulerJob.deleted_at.is_(None), SchedulerJob.code == code)
        ).scalar_one_or_none()
        if job is None:
            return None
        cat_int_ids = self.category_ids_for_job(code)
        return _job_to_dict(job, category_ids=cat_int_ids)

    def category_ids_for_job(self, code: str) -> list[int]:
        """返 code 这个 job 的所有 category int id (按 sort_order 升序, 即 1..N)."""
        rows = self.db.execute(
            select(SchedulerJobCategory.id)
            .join(
                SchedulerJobCategoryMapping,
                SchedulerJobCategoryMapping.category_id == SchedulerJobCategory.id,
            )
            .join(
                SchedulerJob,
                SchedulerJob.id == SchedulerJobCategoryMapping.job_id,
            )
            .where(
                SchedulerJob.deleted_at.is_(None),
                SchedulerJobCategoryMapping.deleted_at.is_(None),
                SchedulerJobCategory.deleted_at.is_(None),
                SchedulerJob.code == code,
            )
            .order_by(SchedulerJobCategory.sort_order.asc())
        ).all()
        cat_uuid_to_int = self._category_uuid_to_int_id()
        return sorted(cat_uuid_to_int[r[0]] for r in rows if r[0] in cat_uuid_to_int)

    # ---- daily statistics (读) ----

    def daily_stats(self, days: int = 14) -> list[dict[str, Any]]:
        """聚合近 N 天每天 run_history 条数 (按 status 分类).

        返 [{date: '2026-06-07', total: 5, success: 4, failed: 1, skipped: 0}, …]
        按 date 升序.
        """
        rows = self.db.execute(
            text("""
                SELECT
                    DATE(started_at)                AS date,
                    COUNT(*)                        AS total,
                    COUNT(*) FILTER (WHERE status = 'success') AS success,
                    COUNT(*) FILTER (WHERE status = 'failed')  AS failed,
                    COUNT(*) FILTER (WHERE status = 'skipped') AS skipped
                FROM app.scheduler_job_run_history
                WHERE started_at >= (NOW() - make_interval(days => :days))
                  AND started_at < (NOW() + '1 day'::interval)
                GROUP BY DATE(started_at)
                ORDER BY date ASC
            """),
            {"days": days},
        ).all()

        return [
            {
                "date": str(r[0]),
                "total": int(r[1]),
                "success": int(r[2]),
                "failed": int(r[3]),
                "skipped": int(r[4]),
            }
            for r in rows
        ]

    # ---- jobs (写) ----

    def set_enabled_by_code(self, code: str, enabled: bool) -> bool:
        """更新 ``scheduler_jobs.is_enabled``. 返 True = 命中一行."""
        result = self.db.execute(
            update(SchedulerJob)
            .where(SchedulerJob.deleted_at.is_(None), SchedulerJob.code == code)
            .values(is_enabled=bool(enabled))
        )
        return result.rowcount > 0

    def soft_delete_by_code(self, code: str) -> bool:
        """软删 (deleted_at = now). 之后该 job 不出现在 list_jobs()."""
        result = self.db.execute(
            update(SchedulerJob)
            .where(SchedulerJob.deleted_at.is_(None), SchedulerJob.code == code)
            .values(deleted_at=func.now())
        )
        return result.rowcount > 0