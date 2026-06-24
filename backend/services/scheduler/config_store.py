"""DB-backed scheduler config store — 替代 ``scheduler/<code>_job.json`` 文件读写.

用法::

    from backend.services.scheduler.config_store import load_config, save_config

    cfg = load_config("turnover")
    cfg["total_runs"] += 1
    save_config("turnover", cfg)

所有配置 + 运行时追踪字段统一存到 ``app.scheduler_jobs.extra`` (JSONB).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update

from backend.models.scheduler import (
    SchedulerJob,
    SchedulerJobCategory,
    SchedulerJobCategoryMapping,
)
from backend.services.scheduler.job_description_catalog import (
    get_job_description,
    iter_job_descriptions,
)

logger = logging.getLogger(__name__)


def _session():
    from backend.config.database import session_scope
    return session_scope


def load_config(code: str) -> dict[str, Any]:
    """从 ``app.scheduler_jobs.extra`` 读 job config.  DB 不可用时返 {}."""
    try:
        with _session()() as db:
            row = db.execute(
                select(SchedulerJob.extra).where(
                    SchedulerJob.code == code,
                    SchedulerJob.deleted_at.is_(None),
                )
            ).scalar_one_or_none()
            if row is None:
                return {}
            return dict(row)
    except Exception as exc:
        logger.warning("config_store.load_config(%s) failed: %s", code, exc)
        return {}


def save_config(code: str, config: dict[str, Any]) -> bool:
    """覆写 ``app.scheduler_jobs.extra``.  返 True = 更新成功."""
    try:
        with _session()() as db:
            result = db.execute(
                update(SchedulerJob)
                .where(
                    SchedulerJob.code == code,
                    SchedulerJob.deleted_at.is_(None),
                )
                .values(extra=config, updated_at=func.now())
            )
            db.flush()
            return result.rowcount > 0
    except Exception as exc:
        logger.warning("config_store.save_config(%s) failed: %s", code, exc)
        return False


def _sync_job_category_mappings(
    db,
    job: SchedulerJob,
    category_codes: list[str],
    category_sort_orders: dict[str, int] | None = None,
) -> None:
    if not category_codes:
        return

    cats = db.execute(
        select(SchedulerJobCategory)
        .where(
            SchedulerJobCategory.code.in_(category_codes),
            SchedulerJobCategory.deleted_at.is_(None),
        )
    ).scalars().all()
    cat_by_code = {c.code: c for c in cats}
    existing = {
        row.category_id: row
        for row in db.execute(
            select(SchedulerJobCategoryMapping).where(
                SchedulerJobCategoryMapping.job_id == job.id,
                SchedulerJobCategoryMapping.deleted_at.is_(None),
            )
        ).scalars().all()
    }

    for index, category_code in enumerate(category_codes, start=1):
        cat = cat_by_code.get(category_code)
        if cat is None:
            continue
        sort_order = int((category_sort_orders or {}).get(category_code, index * 10))
        mapping = existing.get(cat.id)
        if mapping is not None:
            mapping.sort_order = sort_order
            mapping.deleted_at = None
            mapping.updated_at = func.now()
            continue
        db.add(
            SchedulerJobCategoryMapping(
                job_id=job.id,
                category_id=cat.id,
                sort_order=sort_order,
            )
        )


def register_job(
    code: str,
    name: str,
    description: str,
    service_module: str,
    service_class: str,
    config_file: str | None = None,
    default_config: dict[str, Any] | None = None,
    category_codes: list[str] | None = None,
    category_sort_orders: dict[str, int] | None = None,
) -> bool:
    """向 ``app.scheduler_jobs`` 注册/更新一个 job (幂等).

    只有 code 匹配且 deleted_at IS NULL 的行会被 UPDATE;
    没有则 INSERT.  等同于以前的 ``_register_*_job()`` + ``jobs.json`` 写入.
    """
    try:
        description = get_job_description(code, description)
        with _session()() as db:
            existing = db.execute(
                select(SchedulerJob).where(
                    SchedulerJob.code == code,
                    SchedulerJob.deleted_at.is_(None),
                )
            ).scalar_one_or_none()

            extra = default_config or {}

            if existing:
                job = existing
                job.name = name
                job.description = description
                job.service_module = service_module
                job.service_class = service_class
                job.config_file = config_file or ""
                job.extra = {**extra, **(job.extra or {})}
                job.updated_at = func.now()
                job.deleted_at = None
            else:
                job = SchedulerJob(
                    code=code,
                    name=name,
                    description=description,
                    service_module=service_module,
                    service_class=service_class,
                    config_file=config_file or "",
                    is_enabled=True,
                    extra=extra,
                    registered_at=datetime.now(),
                )
                db.add(job)
            db.flush()
            _sync_job_category_mappings(
                db,
                job,
                category_codes or [],
                category_sort_orders,
            )
            db.flush()
            return True
    except Exception as exc:
        logger.error("config_store.register_job(%s) failed: %s", code, exc)
        return False


def sync_job_descriptions() -> int:
    """把 catalog 中的 description 同步到已有的 ``app.scheduler_jobs`` 行.

    只在 description 实际变更时更新，返回更新的行数。
    """
    try:
        with _session()() as db:
            rows = db.execute(
                select(SchedulerJob).where(SchedulerJob.deleted_at.is_(None))
            ).scalars().all()
            catalog = dict(iter_job_descriptions())
            updated = 0
            for row in rows:
                description = catalog.get(row.code)
                if description and row.description != description:
                    row.description = description
                    row.updated_at = func.now()
                    updated += 1
            if updated:
                db.flush()
            return updated
    except Exception as exc:
        logger.warning("config_store.sync_job_descriptions() failed: %s", exc)
        return 0
