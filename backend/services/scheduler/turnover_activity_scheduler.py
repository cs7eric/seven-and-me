"""成交活跃度 (Turnover Activity) duckdb 回填 scheduler.

单 job:
  - 工作日 17:12 触发 (cron ``12 17 * * mon-fri``)
  - 调 ``scripts/backfill_turnover_activity.py --days=3``

校验: subprocess 成功后, 检查 turnover_activity_daily.score 不为 NULL 且 > 0.

启动: :mod:`backend.bootstrap` 调 :func:`start_turnover_activity_scheduler`.
关闭: ``MINIMAX_TURNOVER_ACTIVITY_SCHEDULER_ENABLED=0``.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.services.scheduler.backfill_validator import validate_scalar
from backend.services.scheduler.config_store import load_config, save_config, register_job
from backend.services.scheduler.job_history import record_run, trigger_type
from backend.services.stock.trading_day_resolver import resolve_target_trading_day

logger = logging.getLogger(__name__)

TURNOVER_ACTIVITY_CRON = "12 17 * * mon-fri"
_JOB_ID = "turnover_activity_refresh"
_SCRIPT_PATH_KEY = "turnover_activity_script"
_JOB_TIMEOUT_SECONDS = 5 * 60

_scheduler: BackgroundScheduler | None = None
_scheduler_lock = threading.Lock()


def is_turnover_activity_scheduler_enabled() -> bool:
    return os.environ.get("MINIMAX_TURNOVER_ACTIVITY_SCHEDULER_ENABLED", "1") != "0"


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_script_path() -> str:
    return str(_repo_root() / "scripts" / "backfill_turnover_activity.py")


def _job_default_status() -> dict[str, Any]:
    return {
        "name": _JOB_ID,
        "lastRunAt": None, "lastRunOk": None, "lastRunError": None,
        "lastDurationSeconds": None, "lastDaysRequested": None,
        "totalRuns": 0, "totalFailures": 0, "schedulerStartedAt": None,
    }


def _load_job_status() -> dict[str, Any]:
    cfg = load_config("turnover_activity_refresh")
    return cfg if cfg else _job_default_status()


def _save_job_status(status: dict[str, Any]) -> None:
    save_config("turnover_activity_refresh", status)


def _register_job(job_id: str, name: str, next_run_time: str | None) -> None:
    register_job(
        code="turnover_activity_refresh", name=name,
        description=(
            "MSI Factor 2: turnover (成交活跃度, weight 15%). "
            "工作日 17:12 触发, 调 scripts/backfill_turnover_activity.py --days=3, "
            "从 market_overview_daily.total_amount 计算 ratio = 全市场成交额/20日均 -> 3年历史分位 0-100. "
            "依赖 market_overview_daily 17:10 必须先落 total_amount, 落 duckdb.turnover_activity_daily."
        ),
        service_module="backend.services.scheduler.turnover_activity_scheduler",
        service_class="TurnoverActivityScheduler",
        config_file="turnover_activity_job.json",
        default_config=_job_default_status(),
    )


def job_run_backfill() -> dict:
    now = _beijing_now()
    target_date = resolve_target_trading_day(now.date())
    status = _load_job_status()
    t0 = time.time()
    start_at_iso = now.isoformat(timespec="seconds")
    status["lastRunAt"] = start_at_iso
    status["lastTargetTradeDate"] = target_date.isoformat()

    script_path = status.get(_SCRIPT_PATH_KEY) or _default_script_path()
    script = Path(script_path)
    if not script.is_absolute():
        script = _repo_root() / script
    if not script.exists():
        msg = "script not found: {}".format(script)
        logger.error("turnover_activity: %s", msg)
        status["lastRunOk"] = False
        status["lastRunError"] = msg
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        _save_job_status(status)
        record_run(_JOB_ID, status="failed", duration_seconds=status.get("lastDurationSeconds"),
                   start_at=start_at_iso, end_at=datetime.now().isoformat(timespec="seconds"),
                   error=status.get("lastRunError"))
        return {"ok": False, "error": msg}

    try:
        script_env = {**os.environ, "MINIMAX_TARGET_TRADE_DATE": target_date.isoformat()}
        r = subprocess.run(
            [sys.executable, "-u", str(script), "--days=3"],
            cwd=str(_repo_root()), check=False, capture_output=True, text=True,
            env=script_env, timeout=_JOB_TIMEOUT_SECONDS,
        )
        elapsed = time.time() - t0
        status["lastDurationSeconds"] = round(elapsed, 1)
        status["lastDaysRequested"] = 3

        if r.returncode == 0:
            valid, err_msg = validate_scalar("turnover_activity_daily", "score", target_date)
            if not valid:
                status["lastRunOk"] = False
                status["lastRunError"] = "[校验失败] " + str(err_msg)
                status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
                logger.warning("turnover_activity validation failed in %.1fs: %s", elapsed, err_msg)
            else:
                status["lastRunOk"] = True
                status["lastRunError"] = None
                status["totalRuns"] = int(status.get("totalRuns") or 0) + 1
                logger.info("turnover_activity ok in %.1fs", elapsed)
        else:
            err_tail = (r.stderr or r.stdout or "")[-500:].strip()
            status["lastRunOk"] = False
            status["lastRunError"] = err_tail or "exit={}".format(r.returncode)
            status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
            logger.warning("turnover_activity failed in %.1fs: exit=%d\n%s", elapsed, r.returncode, err_tail)
    except subprocess.TimeoutExpired:
        status["lastRunOk"] = False
        status["lastRunError"] = "timeout (>{}s)".format(_JOB_TIMEOUT_SECONDS)
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning("turnover_activity timeout after %.1fs", time.time() - t0)
    except Exception as exc:
        status["lastRunOk"] = False
        status["lastRunError"] = "{}: {}".format(type(exc).__name__, exc)[:300]
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning("turnover_activity crashed: %s\n%s", exc, traceback.format_exc())

    _save_job_status(status)
    record_run(_JOB_ID, status="success" if status.get("lastRunOk") else "failed",
               duration_seconds=status.get("lastDurationSeconds"),
               start_at=start_at_iso, end_at=datetime.now().isoformat(timespec="seconds"),
               error=status.get("lastRunError"))
    return {"ok": bool(status.get("lastRunOk"))}


def _job_run_backfill() -> None:
    job_run_backfill()


def start_turnover_activity_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    with _scheduler_lock:
        if _scheduler is not None:
            return
        status = _load_job_status()
        if not status.get("enabled", True):
            logger.info("[TurnoverActivityScheduler] disabled by config, not started")
            return
        sched = BackgroundScheduler(timezone="Asia/Shanghai")
        sched.add_job(_job_run_backfill, CronTrigger.from_crontab(TURNOVER_ACTIVITY_CRON),
                       id=_JOB_ID, max_instances=1, coalesce=True)
        sched.start()
        _scheduler = sched
        status["schedulerStartedAt"] = _beijing_now().isoformat(timespec="seconds")
        _save_job_status(status)
        _register_job(_JOB_ID, "turnover_activity_refresh (17:12, 成交活跃度回填 duckdb)", None)
        logger.info("turnover_activity_scheduler started: cron=%s", TURNOVER_ACTIVITY_CRON)
    status = _load_job_status()
    status["running"] = True
    _save_job_status(status)


def stop_turnover_activity_scheduler() -> None:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            logger.info("turnover_activity_scheduler stopped")
    status = _load_job_status()
    status["running"] = False
    status["stoppedAt"] = _beijing_now().isoformat(timespec="seconds")
    _save_job_status(status)


def get_turnover_activity_scheduler_status() -> dict[str, Any]:
    status = _load_job_status()
    status["running"] = _scheduler is not None
    return status


def run_turnover_activity_now() -> dict[str, Any]:
    with trigger_type("manual"):
        result = job_run_backfill()
    status = get_turnover_activity_scheduler_status()
    return {"ok": bool(result.get("ok")), "items": [status], "count": 1,
            "failed_count": 0 if result.get("ok") else 1}


def get_turnover_activity_scheduler() -> BackgroundScheduler | None:
    return _scheduler
