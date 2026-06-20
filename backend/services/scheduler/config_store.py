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

from backend.models.scheduler import SchedulerJob

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


def register_job(
    code: str,
    name: str,
    description: str,
    service_module: str,
    service_class: str,
    config_file: str | None = None,
    default_config: dict[str, Any] | None = None,
) -> bool:
    """向 ``app.scheduler_jobs`` 注册/更新一个 job (幂等).

    只有 code 匹配且 deleted_at IS NULL 的行会被 UPDATE;
    没有则 INSERT.  等同于以前的 ``_register_*_job()`` + ``jobs.json`` 写入.
    """
    try:
        with _session()() as db:
            existing = db.execute(
                select(SchedulerJob).where(
                    SchedulerJob.code == code,
                    SchedulerJob.deleted_at.is_(None),
                )
            ).scalar_one_or_none()

            extra = default_config or {}

            if existing:
                existing.name = name
                existing.description = description
                existing.service_module = service_module
                existing.service_class = service_class
                existing.config_file = config_file or ""
                existing.extra = {**extra, **(existing.extra or {})}
                existing.updated_at = func.now()
                existing.deleted_at = None
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
            return True
    except Exception as exc:
        logger.error("config_store.register_job(%s) failed: %s", code, exc)
        return False
