"""TDX 日线数据初始回填 (Initial Backfill) scheduler.

单 job:
  - 工作日 16:45 触发 (cron ``45 16 * * mon-fri``)
  - 调 ``scripts/initial_backfill.py``
  - 解析 TDX .day 二进制文件 -> duckdb daily_raw (INSERT OR IGNORE 幂等)
  - 依赖: tdx_hsjday_download (16:30) 必须先把 hsjday/ 数据下载/更新好

校验: subprocess 成功后, 检查 daily_raw 在目标日至少有 100 行.

启动: :mod:`backend.bootstrap` 调 :func:`start_initial_backfill_scheduler`.
关闭: ``MINIMAX_INITIAL_BACKFILL_SCHEDULER_ENABLED=0``.
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

from backend.services.scheduler.backfill_validator import validate_count
from backend.services.scheduler.config_store import register_job
from backend.services.scheduler.status_store import load_status, save_status
from backend.services.scheduler.time_utils import cst_now_str
from backend.services.scheduler.job_history import record_run, trigger_type
from backend.services.stock.trading_day_resolver import resolve_target_trading_day

logger = logging.getLogger(__name__)

INITIAL_BACKFILL_CRON = "45 16 * * mon-fri"
_JOB_ID = "initial_backfill_refresh"
_SCRIPT_PATH_KEY = "initial_backfill_script"
_JOB_TIMEOUT_SECONDS = 15 * 60

_scheduler: BackgroundScheduler | None = None
_scheduler_lock = threading.Lock()


def is_initial_backfill_scheduler_enabled() -> bool:
    return os.environ.get("MINIMAX_INITIAL_BACKFILL_SCHEDULER_ENABLED", "1") != "0"


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_script_path() -> str:
    return str(_repo_root() / "scripts" / "initial_backfill.py")


def _job_default_status() -> dict[str, Any]:
    return {
        "name": _JOB_ID,
        "lastRunAt": None, "lastRunOk": None, "lastRunError": None,
        "lastDurationSeconds": None, "lastFilesParsed": None,
        "totalRuns": 0, "totalFailures": 0, "schedulerStartedAt": None,
    }


def _load_job_status() -> dict[str, Any]:
    cfg = load_status("initial_backfill_refresh")
    return cfg if cfg else _job_default_status()


def _save_job_status(status: dict[str, Any]) -> None:
    save_status("initial_backfill_refresh", status)


def _register_job(job_id: str, name: str, next_run_time: str | None) -> None:
    register_job(
        code="initial_backfill_refresh", name=name,
        description=(
            "MSI 上游: TDX 日线数据解析入库. "
            "工作日 16:45 触发, 调 scripts/initial_backfill.py, "
            "解析 TDX .day 二进制文件 -> duckdb daily_raw (INSERT OR IGNORE 幂等). "
            "依赖 tdx_hsjday_download 16:30 必须先下载好 hsjday/ 数据."
        ),
        service_module="backend.services.scheduler.initial_backfill_scheduler",
        service_class="InitialBackfillScheduler",
        config_file="initial_backfill_job.json",
        default_config=_job_default_status(),
    )


def job_run_backfill() -> dict:
    now = _beijing_now()
    target_date = resolve_target_trading_day(now.date())
    status = _load_job_status()
    t0 = time.time()
    start_at_iso = now.isoformat(timespec="seconds")
    cst_time = cst_now_str()
    status["lastRunAt"] = start_at_iso
    status["lastTargetTradeDate"] = target_date.isoformat()

    script_path = status.get(_SCRIPT_PATH_KEY) or _default_script_path()
    script = Path(script_path)
    if not script.is_absolute():
        script = _repo_root() / script
    if not script.exists():
        msg = "script not found: {}".format(script)
        logger.error("initial_backfill: %s", msg)
        status["lastRunOk"] = False
        status["lastRunError"] = f"{cst_time} {msg}"
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        _save_job_status(status)
        record_run(_JOB_ID, status="failed", duration_seconds=status.get("lastDurationSeconds"),
                   start_at=start_at_iso, end_at=datetime.now().isoformat(timespec="seconds"),
                   error=status.get("lastRunError"),
                   message=status.get("lastMessage"))
        return {"ok": False, "error": msg}

    try:
        script_env = {**os.environ, "MINIMAX_TARGET_TRADE_DATE": target_date.isoformat()}
        r = subprocess.run(
            [sys.executable, "-u", str(script), "--no-resume"],
            cwd=str(_repo_root()), check=False, capture_output=True, text=True,
            env=script_env, timeout=_JOB_TIMEOUT_SECONDS,
        )
        elapsed = time.time() - t0
        status["lastDurationSeconds"] = round(elapsed, 1)

        stdout = (r.stdout or "") + "\n" + (r.stderr or "")
        m = re.search(r"parsed\s+(\d+)\s+files", stdout)
        if m:
            status["lastFilesParsed"] = int(m.group(1))

        if r.returncode == 0:
            valid, err_msg = validate_count("daily_raw", target_date, min_rows=1000)
            if not valid:
                status["lastRunOk"] = False
                status["lastRunError"] = f"{cst_time} " + "[校验失败] " + str(err_msg)
                status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
                logger.warning("initial_backfill validation failed in %.1fs: %s", elapsed, err_msg)
            else:
                status["lastRunOk"] = True
                status["lastRunError"] = None

                status["lastMessage"] = f"{cst_time}  ok, parsed {status.get('lastFilesParsed', '?')} files → daily_raw"
                status["totalRuns"] = int(status.get("totalRuns") or 0) + 1
                logger.info("initial_backfill ok in %.1fs: files=%s", elapsed, status.get("lastFilesParsed"))
        else:
            err_tail = (r.stderr or r.stdout or "")[-500:].strip()
            status["lastRunOk"] = False
            status["lastRunError"] = f"{cst_time} " + str(err_tail or "exit={}".format(r.returncode))
            status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
            logger.warning("initial_backfill failed in %.1fs: exit=%d\n%s", elapsed, r.returncode, err_tail)
    except subprocess.TimeoutExpired:
        status["lastRunOk"] = False
        status["lastRunError"] = f"{cst_time} " + "timeout (>{}s)".format(_JOB_TIMEOUT_SECONDS)
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning("initial_backfill timeout after %.1fs", time.time() - t0)
    except Exception as exc:
        status["lastRunOk"] = False
        status["lastRunError"] = f"{cst_time} " + "{}: {}".format(type(exc).__name__, exc)[:300]
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning("initial_backfill crashed: %s\n%s", exc, traceback.format_exc())

    _save_job_status(status)
    record_run(_JOB_ID, status="success" if status.get("lastRunOk") else "failed",
               duration_seconds=status.get("lastDurationSeconds"),
               start_at=start_at_iso, end_at=datetime.now().isoformat(timespec="seconds"),
               error=status.get("lastRunError"),
               message=status.get("lastMessage"))
    return {"ok": bool(status.get("lastRunOk"))}


def _job_run_backfill() -> None:
    job_run_backfill()


def start_initial_backfill_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    with _scheduler_lock:
        if _scheduler is not None:
            return
        status = _load_job_status()
        if not status.get("enabled", True):
            logger.info("[InitialBackfillScheduler] disabled by config, not started")
            return
        sched = BackgroundScheduler(timezone="Asia/Shanghai")
        sched.add_job(_job_run_backfill, CronTrigger.from_crontab(INITIAL_BACKFILL_CRON),
                       id=_JOB_ID, max_instances=1, coalesce=True)
        sched.start()
        _scheduler = sched
        status["schedulerStartedAt"] = _beijing_now().isoformat(timespec="seconds")
        _register_job(_JOB_ID, "initial_backfill_refresh (16:45, TDX -> duckdb daily_raw)", None)
        _save_job_status(status)
        logger.info("initial_backfill_scheduler started: cron=%s", INITIAL_BACKFILL_CRON)
    status = _load_job_status()
    status["running"] = True
    _save_job_status(status)


def stop_initial_backfill_scheduler() -> None:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            logger.info("initial_backfill_scheduler stopped")
    status = _load_job_status()
    status["running"] = False
    status["stoppedAt"] = _beijing_now().isoformat(timespec="seconds")
    _save_job_status(status)


def get_initial_backfill_scheduler_status() -> dict[str, Any]:
    status = _load_job_status()
    status["running"] = _scheduler is not None
    return status


def run_initial_backfill_now() -> dict[str, Any]:
    with trigger_type("manual"):
        result = job_run_backfill()
    status = get_initial_backfill_scheduler_status()
    return {"ok": bool(result.get("ok")), "items": [status], "count": 1,
            "failed_count": 0 if result.get("ok") else 1}


def get_initial_backfill_scheduler() -> BackgroundScheduler | None:
    return _scheduler
