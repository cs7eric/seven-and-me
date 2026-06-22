"""DB-backed scheduler runtime status store — 替代 JSON 文件和 config_store 的状态读写.

统一读写 ``app.scheduler_job_statuses`` 表.
``config_store.register_job()`` 保留用于 job 注册 (``app.scheduler_jobs``).

用法::

    from backend.services.scheduler.status_store import load_status, save_status

    status = load_status("ma_count_refresh") or _job_default_status()
    status["lastRunOk"] = True
    status["lastRunError"] = None
    save_status("ma_count_refresh", status)

字段映射 (scheduler dict key → scheduler_job_statuses column):

============================  ==========================
dict key                       column
============================  ==========================
enabled                        is_enabled
running                        is_running
lastRunAt                      last_run_at
lastRunOk                      last_run_ok
lastRunError                   last_run_error_message
lastStatus                     last_run_status
lastDurationSeconds            last_duration_seconds
lastTargetsProcessed           last_targets_processed
totalRuns                      total_runs
totalFailures                  total_failures
schedulerStartedAt             scheduler_started_at
stoppedAt                      stopped_at
schedule                       schedule
============================  ==========================

未映射的字段 → ``extra`` JSONB.

兼容 snake_case 旧字段: ``last_run_at``, ``last_error``, ``last_duration_seconds``,
``total_runs``, ``last_status``, ``last_targets_processed`` 等 (读取时两套都认).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import select

from backend.models.scheduler import SchedulerJob, SchedulerJobStatus

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))

# Columns that store CST-origin timestamps (from _beijing_now() / cst_now_str()).
# When the input value is a naive ISO string or naive datetime, assume CST.
_DATETIME_CST_COLUMNS = frozenset({"last_run_at", "scheduler_started_at", "stopped_at"})

# ── 字段映射 ──────────────────────────────────────────────────────────
# scheduler dict key → SchedulerJobStatus column name
_COLUMN_MAP: dict[str, str] = {
    "enabled":               "is_enabled",
    "running":               "is_running",
    "lastRunAt":             "last_run_at",
    "lastRunOk":             "last_run_ok",
    "lastRunError":          "last_run_error_message",
    "lastStatus":            "last_run_status",
    "lastDurationSeconds":   "last_duration_seconds",
    "lastTargetsProcessed":  "last_targets_processed",
    "totalRuns":             "total_runs",
    "totalFailures":         "total_failures",
    "schedulerStartedAt":    "scheduler_started_at",
    "stoppedAt":             "stopped_at",
    "schedule":              "schedule",
}

# snake_case → column (读取兼容)
_SNAKE_MAP: dict[str, str] = {
    "last_run_at":             "last_run_at",
    "last_error":              "last_run_error_message",
    "last_run_error":          "last_run_error_message",
    "last_duration_seconds":   "last_duration_seconds",
    "total_runs":              "total_runs",
    "total_failures":          "total_failures",
    "last_status":             "last_run_status",
    "last_run_ok":             "last_run_ok",
    "last_targets_processed":  "last_targets_processed",
    "scheduler_started_at":    "scheduler_started_at",
    "stopped_at":              "stopped_at",
    "is_enabled":              "is_enabled",
    "is_running":              "is_running",
}

# 反向: column → dict key (camelCase)
_REVERSE_MAP: dict[str, str] = {v: k for k, v in _COLUMN_MAP.items()}

# 反向: column → dict key (snake_case, 兼容旧 scheduler)
_SNAKE_REVERSE: dict[str, str] = {
    "last_run_at":              "last_run_at",
    "last_run_error_message":   "last_error",
    "last_run_ok":              "last_run_ok",
    "last_run_status":          "last_status",
    "last_duration_seconds":    "last_duration_seconds",
    "last_targets_processed":   "last_targets_processed",
    "total_runs":               "total_runs",
    "total_failures":           "total_failures",
    "scheduler_started_at":     "scheduler_started_at",
    "stopped_at":               "stopped_at",
    "is_enabled":               "enabled",
    "is_running":               "running",
}


def _ensure_tz(value: Any, assume_tz: timezone) -> Any:
    """If value is a naive datetime or naive ISO string, make it tz-aware with ``assume_tz``."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=assume_tz)
        return value
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return value
        if dt.tzinfo is None:
            return dt.replace(tzinfo=assume_tz)
        return dt
    return value


def _session():
    from backend.config.database import session_scope
    return session_scope


def _resolve_column(key: str) -> str | None:
    """把 dict key (camelCase 或 snake_case) 映射到 column name. 未映射返 None."""
    if key in _COLUMN_MAP:
        return _COLUMN_MAP[key]
    if key in _SNAKE_MAP:
        return _SNAKE_MAP[key]
    return None


def load_status(code: str) -> dict[str, Any] | None:
    """从 ``app.scheduler_job_statuses`` 读运行时状态, 返 dict (含 extra 合并).

    行不存在或 DB 不可用时返 None.
    """
    try:
        with _session()() as db:
            row = db.execute(
                select(SchedulerJobStatus)
                .join(SchedulerJob, SchedulerJob.id == SchedulerJobStatus.job_id)
                .where(
                    SchedulerJob.code == code,
                    SchedulerJob.deleted_at.is_(None),
                    SchedulerJobStatus.deleted_at.is_(None),
                )
            ).scalar_one_or_none()

            if row is None:
                return None

            # 先过滤 extra 里历史遗留的 alias 字段, 避免它们盖住列里的最新值.
            # 例如老版本把 ``last_error`` / ``last_run_at`` 写进 extra, 如果新列值为
            # None 或调用方只更新 camelCase, 这些遗留 key 会在后续 save_status() 中
            # 重新把旧值写回列, 造成 "lastRunOk 已成功但 lastRunError 仍显示旧失败"。
            result: dict[str, Any] = {
                k: v for k, v in dict(row.extra or {}).items()
                if _resolve_column(k) is None
            }
            for col_name, camel_key in _REVERSE_MAP.items():
                val = getattr(row, col_name, None)
                if val is not None:
                    result[camel_key] = val
            for col_name, snake_key in _SNAKE_REVERSE.items():
                val = getattr(row, col_name, None)
                if val is not None and snake_key not in result:
                    result[snake_key] = val
            return result
    except Exception as exc:
        logger.warning("status_store.load_status(%s) failed: %s", code, exc)
        return None


def save_status(code: str, status: dict[str, Any]) -> bool:
    """把运行时状态写入 ``app.scheduler_job_statuses``. 返 True = 成功.

    列字段走 UPDATE, 其余全部进 ``extra`` JSONB.
    行不存在时自动 INSERT.
    """
    try:
        with _session()() as db:
            # 1) 解析 job_id
            job_row = db.execute(
                select(SchedulerJob.id).where(
                    SchedulerJob.code == code,
                    SchedulerJob.deleted_at.is_(None),
                )
            ).scalar_one_or_none()

            if job_row is None:
                logger.warning(
                    "status_store.save_status(%s): job not found in app.scheduler_jobs", code,
                )
                return False

            job_id = job_row

            # 2) 拆字段: 已知列 vs extra
            columns: dict[str, Any] = {"job_id": job_id}
            extra: dict[str, Any] = {}
            pending_columns: dict[str, Any] = {}

            # 先处理 snake_case/legacy alias, 再处理 camelCase.
            # 这样当 status 同时带 ``last_error`` 和 ``lastRunError`` 时, 新的 camelCase
            # 会覆盖旧 alias, 避免旧值把本轮刚清掉的错误再次写回数据库。
            ordered_items = [
                (k, v) for k, v in status.items() if k not in _COLUMN_MAP
            ] + [
                (k, v) for k, v in status.items() if k in _COLUMN_MAP
            ]

            for key, value in ordered_items:
                col = _resolve_column(key)
                if col:
                    if value is not None and col in _DATETIME_CST_COLUMNS:
                        value = _ensure_tz(value, _CST)
                    pending_columns[col] = value
                else:
                    extra[key] = value

            total_runs = pending_columns.get("total_runs")
            total_failures = pending_columns.get("total_failures")
            if (
                isinstance(total_runs, int)
                and isinstance(total_failures, int)
                and total_failures > total_runs
            ):
                pending_columns["total_runs"] = total_failures

            columns.update(pending_columns)

            columns["extra"] = extra
            columns["updated_at"] = datetime.now(timezone.utc)

            # 3) 先 UPDATE, 没命中再 INSERT.
            # app.scheduler_job_statuses 只有 partial unique index(job_id) where deleted_at is null，
            # 某些环境下 ON CONFLICT 推断这个索引会失败；这里显式走 update-or-insert 更稳。
            existing = db.execute(
                select(SchedulerJobStatus).where(
                    SchedulerJobStatus.job_id == job_id,
                    SchedulerJobStatus.deleted_at.is_(None),
                )
            ).scalar_one_or_none()

            if existing is not None:
                for col, value in columns.items():
                    if col == "job_id":
                        continue
                    setattr(existing, col, value)
            else:
                db.add(
                    SchedulerJobStatus(
                        **columns,
                    )
                )

            db.flush()
            return True
    except Exception as exc:
        logger.warning("status_store.save_status(%s) failed: %s", code, exc)
        return False
