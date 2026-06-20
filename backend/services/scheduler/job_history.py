"""Job history: 每次 scheduler 跑完自动写一条记录, 供前端渲染"上次/最近 50 次" 列表.

设计:
  - 存储: 每个 job 自己的 status JSON 顶层加 ``history`` 数组 (跟 last_run_* 字段并列)
  - 容量: 每 job 最多 50 条, 超了 FIFO 删老的
  - 字段: ``{start_at, end_at, trigger_type, status, error, duration_seconds}``
    - trigger_type: "auto" (cron) | "manual" (前端 /api/scheduler/jobs/<id>/trigger 触发)
  - application_analysis 是 in-memory scheduler (没 status JSON), 它的 history 写到
    ``reference/application-analysis/scheduler.json`` 里, 跟 per-target last_run map 同文件

trigger_type 通过 ``contextvars.ContextVar`` 传递, 不用改 _job_run_* 签名:
  - cron 路径: 不设 → 默认 "auto"
  - API trigger 路径: 在调 _job_run_* 之前 ``set_trigger_type("manual")`` → 该 worker 看到 "manual"
"""
from __future__ import annotations

import contextvars
import json
import logging
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Literal

from backend.config.settings import BASE_DIR
from backend.utils.json_io import read_json_file, write_json_file

logger = logging.getLogger(__name__)

MAX_HISTORY_PER_JOB = 50

# Trigger type 通过 ContextVar 跨函数传递, 跟 threading.local 比, 不会污染其他请求 / cron tick
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
    """Context manager: 在 with 块内 set_trigger_type(t), 退出恢复.

    用法::

        with trigger_type("manual"):
            _job_run_incremental()
    """
    token = _trigger_type_var.set(t)
    try:
        yield
    finally:
        _trigger_type_var.reset(token)


# ---------------------------------------------------------------------------
# 状态文件路径解析 (跟 backend/api/scheduler.py 的 _load_job_config 一致)
# ---------------------------------------------------------------------------

def _jobs_registry_path() -> Path:
    return BASE_DIR / "scheduler" / "jobs.json"


def _load_jobs_registry() -> dict[str, Any]:
    p = _jobs_registry_path()
    if not p.exists():
        return {"version": 1, "jobs": []}
    data = read_json_file(p, {"version": 1, "jobs": []})
    if isinstance(data, list):
        return {"version": 1, "jobs": data}
    if not isinstance(data, dict):
        return {"version": 1, "jobs": []}
    return data


def _resolve_status_path(job_id: str) -> Path | None:
    """跟 api/scheduler.py._resolve_config_path 一样的 fallback 逻辑, 但返回 status 文件路径.

    优先级:
      1. application_analysis 特殊: reference/application-analysis/scheduler.json
      2. jobs.json 注册表里查 config_file
      3. 注册表没找到 (scheduler 未启动) → 退化到 scheduler/{job_id}_job.json
         (覆盖 risk_appetite_refresh / ma_count_refresh / volatility_sentiment_refresh
         这几个只在启动时注册的 job, smoke test 时 scheduler 没起也找得到文件)
    """
    if job_id == "application_analysis":
        return (BASE_DIR / "reference" / "application-analysis" / "scheduler.json").resolve()
    reg = _load_jobs_registry()
    entry = next((j for j in reg.get("jobs", []) if j.get("id") == job_id), None)
    if entry:
        config_file = entry.get("config_file") or ""
        if config_file:
            primary = (BASE_DIR / config_file).resolve()
            if primary.exists():
                return primary
            fallback = (BASE_DIR / "scheduler" / Path(config_file).name).resolve()
            if fallback.exists():
                return fallback
            return primary
    # 注册表没找到 → 试 scheduler/{job_id}_job.json (兜底)
    fallback = (BASE_DIR / "scheduler" / f"{job_id}_job.json").resolve()
    if fallback.exists():
        return fallback
    # 一些历史命名不一致的特例 (scheduler 自己注册了别的 id, 但 status 文件名不同)
    _NAME_ALIASES = {
        "risk_appetite_refresh": "risk_appetite_job.json",
        "ma_count_refresh": "ma_count_job.json",
        "volatility_sentiment_refresh": "volatility_sentiment_job.json",
    }
    alias = _NAME_ALIASES.get(job_id)
    if alias:
        candidate = (BASE_DIR / "scheduler" / alias).resolve()
        if candidate.exists():
            return candidate
    return None


# 每个 status 文件并发写用, 简单 lock (同一 job 内串行, 不同 job 并行)
_file_locks: dict[str, threading.Lock] = {}
_file_locks_guard = threading.Lock()


def _file_lock(path: Path) -> threading.Lock:
    key = str(path)
    with _file_locks_guard:
        lock = _file_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _file_locks[key] = lock
        return lock


# ---------------------------------------------------------------------------
# 读 / 写
# ---------------------------------------------------------------------------

def _load_status_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        # 写时再创建
        return {}
    try:
        return read_json_file(path, {}) or {}
    except Exception as exc:
        logger.debug("job_history load %s failed: %s", path, exc)
        return {}


def record_run(
    job_id: str,
    *,
    status: HistoryStatus,
    duration_seconds: float | None,
    start_at: str,
    end_at: str,
    error: str | None = None,
    trigger_type: TriggerType | None = None,
) -> dict[str, Any] | None:
    """写一条 history entry 到 job_id 自己的 status JSON. 返写入的 entry.

    不抛错 (history 写失败不应阻塞 scheduler 主流程), 只 log.
    """
    path = _resolve_status_path(job_id)
    if path is None:
        logger.debug("job_history: no status path for %s, skip", job_id)
        return None

    entry = {
        "start_at": start_at,
        "end_at": end_at,
        "trigger_type": trigger_type or get_trigger_type(),
        "status": status,
        "error": error,
        "duration_seconds": round(duration_seconds, 2) if duration_seconds is not None else None,
    }

    lock = _file_lock(path)
    try:
        with lock:
            payload = _load_status_payload(path)
            history = payload.get("history") or []
            if not isinstance(history, list):
                history = []
            history.append(entry)
            # FIFO 截断
            if len(history) > MAX_HISTORY_PER_JOB:
                history = history[-MAX_HISTORY_PER_JOB:]
            payload["history"] = history
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json_file(path, payload)
    except Exception as exc:
        logger.warning("job_history.record_run %s failed: %s", job_id, exc)
        return None
    return entry


def get_history(job_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """读 job_id 的 history 列表 (新→旧), 限 limit 条."""
    path = _resolve_status_path(job_id)
    if path is None or not path.exists():
        return []
    try:
        payload = _load_status_payload(path)
    except Exception as exc:
        logger.debug("job_history.get_history %s failed: %s", job_id, exc)
        return []
    history = payload.get("history") or []
    if not isinstance(history, list):
        return []
    # 新→旧
    out = list(reversed(history))
    if limit > 0:
        out = out[:limit]
    return out


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
