"""Job history: 每次 scheduler 跑完自动写一条记录到 app.scheduler_job_run_history.

trigger_type 通过 ``contextvars.ContextVar`` 传递:
  - cron 路径: 不设 → 默认 "auto"
  - API trigger: ``trigger_type("manual")`` context → "manual"
"""
from __future__ import annotations

import contextvars
import logging
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from typing import Any, Iterator, Literal

from sqlalchemy import desc, select, func

from backend.models.scheduler import SchedulerJob, SchedulerJobRunHistory

logger = logging.getLogger(__name__)

# All scheduler _beijing_now() / cst_now_str() produce CST (UTC+8).
# PostgreSQL timestamptz columns need timezone-aware values, otherwise
# naive datetimes are interpreted in the session timezone (often UTC),
# causing an 8-hour offset in the UI.
_CST = timezone(timedelta(hours=8))

MAX_HISTORY_PER_JOB = 50

_trigger_type_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "scheduler_trigger_type", default="auto"
)

TriggerType = Literal["auto", "manual"]
HistoryStatus = Literal["success", "failed", "skipped", "running"]


def set_trigger_type(t: TriggerType) -> None:
    _trigger_type_var.set(t)


def get_trigger_type() -> TriggerType:
    try:
        v = _trigger_type_var.get()
        return v if v in ("auto", "manual") else "auto"
    except LookupError:
        return "auto"


@contextmanager
def trigger_type(t: TriggerType) -> Iterator[None]:
    token = _trigger_type_var.set(t)
    try:
        yield
    finally:
        _trigger_type_var.reset(token)


def _session():
    from backend.config.database import session_scope
    return session_scope


def _resolve_job_uuid(db, code: str):
    """把 job code (如 'initial_backfill_refresh') 解析为 UUID."""
    row = db.execute(
        select(SchedulerJob.id).where(
            SchedulerJob.code == code,
            SchedulerJob.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    return row


def record_run(
    job_id: str,
    *,
    status: HistoryStatus,
    duration_seconds: float | None,
    start_at: str,
    end_at: str,
    error: str | None = None,
    message: str | None = None,
    trigger_type: TriggerType | None = None,
) -> dict[str, Any] | None:
    """写一条 history entry 到 app.scheduler_job_run_history. 返写入的 entry dict.

    不抛错 (history 写失败不应阻塞 scheduler 主流程), 只 log.

    - ``error`` → error_message 列 (失败详情)
    - ``message`` → remark 列 (成功详情, 如 "ok, parsed 12236 files → daily_raw")
    """
    entry = {
        "start_at": start_at,
        "end_at": end_at,
        "trigger_type": trigger_type or get_trigger_type(),
        "status": status,
        "error": error,
        "message": message,
        "duration_seconds": round(duration_seconds, 2) if duration_seconds is not None else None,
    }

    try:
        with _session()() as db:
            job_uuid = _resolve_job_uuid(db, job_id)
            if job_uuid is None:
                logger.warning(
                    "job_history: job code '%s' not found in app.scheduler_jobs (deleted?), skip record_run",
                    job_id,
                )
                return None

            # start_at comes from _beijing_now() = naive CST → make tz-aware
            _start_dt = datetime.fromisoformat(start_at)
            if _start_dt.tzinfo is None:
                _start_dt = _start_dt.replace(tzinfo=_CST)

            # end_at comes from datetime.now() on server (often UTC) → make aware
            _end_dt = datetime.fromisoformat(end_at)
            if _end_dt.tzinfo is None:
                _end_dt = _end_dt.replace(tzinfo=timezone.utc)

            record = SchedulerJobRunHistory(
                job_id=job_uuid,
                started_at=_start_dt,
                ended_at=_end_dt,
                trigger_type=entry["trigger_type"],
                status=entry["status"],
                error_message=error,
                remark=message,
                duration_seconds=entry["duration_seconds"],
            )
            db.add(record)
            db.flush()
            return entry
    except Exception as exc:
        logger.warning("job_history.record_run %s failed: %s", job_id, exc)
        return None


def get_history(job_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """读 job_id 的 history 列表 (新→旧), 限 limit 条."""
    try:
        with _session()() as db:
            job_uuid = _resolve_job_uuid(db, job_id)
            if job_uuid is None:
                return []

            rows = db.execute(
                select(SchedulerJobRunHistory)
                .where(SchedulerJobRunHistory.job_id == job_uuid)
                .order_by(desc(SchedulerJobRunHistory.started_at))
                .limit(limit)
            ).scalars().all()

            return [
                {
                    "start_at": r.started_at.isoformat() if r.started_at else None,
                    "end_at": r.ended_at.isoformat() if r.ended_at else None,
                    "trigger_type": r.trigger_type,
                    "status": r.status,
                    "error": r.error_message,
                    "message": r.remark,
                    "duration_seconds": float(r.duration_seconds) if r.duration_seconds else None,
                }
                for r in rows
            ]
    except Exception as exc:
        logger.debug("job_history.get_history %s failed: %s", job_id, exc)
        return []


__all__ = [
    "set_trigger_type",
    "get_trigger_type",
    "trigger_type",
    "record_run",
    "get_history",
    "MAX_HISTORY_PER_JOB",
    "TriggerType",
    "HistoryStatus",
]
