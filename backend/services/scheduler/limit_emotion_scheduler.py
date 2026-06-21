"""涨跌停情绪 (Limit Emotion) duckdb 回填 scheduler.

单 job:
  - 工作日 17:03 触发 (cron ``3 17 * * mon-fri``, is_trading_day 二次过滤)
  - 调 ``scripts/backfill_limit_emotion_summary.py --days=2 --force``

校验: subprocess 成功后, 检查 limit_emotion_summary_daily.composite_score 不为 NULL 且 > 0.

启动: :mod:`backend.bootstrap` 调 :func:`start_limit_emotion_scheduler`.
关闭: ``MINIMAX_LIMIT_EMOTION_SCHEDULER_ENABLED=0``.
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

from backend.services.scheduler.backfill_validator import fetch_scalar_value, validate_scalar
from backend.services.scheduler.config_store import register_job
from backend.services.scheduler.status_store import load_status, save_status
from backend.services.scheduler.time_utils import cst_now_str
from backend.services.scheduler.job_history import record_run, trigger_type
from backend.services.stock.trading_day_resolver import resolve_target_trading_day

logger = logging.getLogger(__name__)

LIMIT_EMOTION_CRON = "3 17 * * mon-fri"
_JOB_ID = "limit_emotion_refresh"
_SCRIPT_PATH_KEY = "limit_emotion_script"
_JOB_TIMEOUT_SECONDS = 5 * 60

_scheduler: BackgroundScheduler | None = None
_scheduler_lock = threading.Lock()


def is_limit_emotion_scheduler_enabled() -> bool:
    return os.environ.get("MINIMAX_LIMIT_EMOTION_SCHEDULER_ENABLED", "1") != "0"


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_script_path() -> str:
    return str(_repo_root() / "scripts" / "backfill_limit_emotion_summary.py")


def _job_default_status() -> dict[str, Any]:
    return {
        "name": _JOB_ID,
        "lastRunAt": None, "lastRunOk": None, "lastRunError": None,
        "lastDurationSeconds": None, "lastDaysRequested": None, "lastCoverage": None,
        "totalRuns": 0, "totalFailures": 0, "schedulerStartedAt": None,
    }


def _load_job_status() -> dict[str, Any]:
    cfg = load_status("limit_emotion_refresh")
    return cfg if cfg else _job_default_status()


def _save_job_status(status: dict[str, Any]) -> None:
    save_status("limit_emotion_refresh", status)


def _register_job(job_id: str, name: str, next_run_time: str | None) -> None:
    register_job(
        code="limit_emotion_refresh", name=name,
        description=(
            "MSI Factor 6: limit_emotion (涨跌停情绪, weight 15%). "
            "Cron 17:03, 涨跌停比(40%)+炸板率反向(30%)+昨日涨停收益(30%) -> composite -> 3年分位 0-100. "
            "落 duckdb.limit_emotion_summary_daily."
        ),
        service_module="backend.services.scheduler.limit_emotion_scheduler",
        service_class="LimitEmotionScheduler",
        config_file="limit_emotion_job.json",
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
        logger.error("limit_emotion: %s", msg)
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
            [sys.executable, "-u", str(script), "--days=2", "--force"],
            cwd=str(_repo_root()), check=False, capture_output=True, text=True,
            env=script_env, timeout=_JOB_TIMEOUT_SECONDS,
        )
        elapsed = time.time() - t0
        status["lastDurationSeconds"] = round(elapsed, 1)
        status["lastDaysRequested"] = 2

        stdout = (r.stdout or "") + "\n" + (r.stderr or "")
        m = re.search(r"完成:\s*写入\s*(\d+)\s*跳过\s*(\d+)", stdout)
        if m:
            status["lastRowsUpserted"] = int(m.group(1))
            status["lastRowsSkipped"] = int(m.group(2))
        else:
            status["lastRowsUpserted"] = None
            status["lastRowsSkipped"] = None

        if r.returncode == 0:
            # DuckDB 数据校验: 有值且不为 0
            _valid_ok, _valid_err = validate_scalar("limit_emotion_summary_daily", "composite_score", target_date)
            if not _valid_ok:
                status["lastRunOk"] = False
                status["lastRunError"] = f"{cst_time} " + "[校验失败] " + str(_valid_err)
                status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
                logger.warning("limit_emotion validation failed in %.1fs: %s", elapsed, _valid_err)
            else:
                status["lastRunOk"] = True
                status["lastRunError"] = None

                comp_val = fetch_scalar_value("limit_emotion_summary_daily", "composite_score", target_date)
                up = status.get("lastRowsUpserted"); sk = status.get("lastRowsSkipped")
                parts = [f"composite={comp_val:.2f}"] if comp_val is not None else []
                if up is not None:
                    parts.append(f"{up}行" + (f"+{sk}行skip" if sk and sk > 0 else ""))
                parts.append(f"(target={target_date.isoformat()})")
                status["lastMessage"] = " ".join(parts) if comp_val is not None else f"{cst_time}  ok"
                status["totalRuns"] = int(status.get("totalRuns") or 0) + 1
                logger.info("limit_emotion ok in %.1fs: upserted=%s skipped=%s composite=%s",
                            elapsed, status.get("lastRowsUpserted"), status.get("lastRowsSkipped"), comp_val)
        else:
            err_tail = (r.stderr or r.stdout or "")[-500:].strip()
            status["lastRunOk"] = False
            status["lastRunError"] = f"{cst_time} " + str(err_tail or "exit={}".format(r.returncode))
            status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
            logger.warning("limit_emotion failed in %.1fs: exit=%d\n%s", elapsed, r.returncode, err_tail)
    except subprocess.TimeoutExpired:
        status["lastRunOk"] = False
        status["lastRunError"] = f"{cst_time} " + "timeout (>{}s)".format(_JOB_TIMEOUT_SECONDS)
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning("limit_emotion timeout after %.1fs", time.time() - t0)
    except Exception as exc:
        status["lastRunOk"] = False
        status["lastRunError"] = f"{cst_time} " + "{}: {}".format(type(exc).__name__, exc)[:300]
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning("limit_emotion crashed: %s\n%s", exc, traceback.format_exc())

    _save_job_status(status)
    record_run(_JOB_ID, status="success" if status.get("lastRunOk") else "failed",
               duration_seconds=status.get("lastDurationSeconds"),
               start_at=start_at_iso, end_at=datetime.now().isoformat(timespec="seconds"),
               error=status.get("lastRunError"),
               message=status.get("lastMessage"))
    return {"ok": bool(status.get("lastRunOk"))}


def _job_run_backfill() -> None:
    job_run_backfill()


def start_limit_emotion_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    with _scheduler_lock:
        if _scheduler is not None:
            return
        status = _load_job_status()
        if not status.get("enabled", True):
            logger.info("[LimitEmotionScheduler] disabled by config, not started")
            return
        sched = BackgroundScheduler(timezone="Asia/Shanghai")
        sched.add_job(_job_run_backfill, CronTrigger.from_crontab(LIMIT_EMOTION_CRON),
                       id=_JOB_ID, max_instances=1, coalesce=True)
        sched.start()
        _scheduler = sched
        status["schedulerStartedAt"] = _beijing_now().isoformat(timespec="seconds")
        _register_job(_JOB_ID, "limit_emotion_refresh (17:03 工作日, 涨跌停情绪综合分回填 duckdb)", None)
        _save_job_status(status)
        logger.info("limit_emotion_scheduler started: cron=%s", LIMIT_EMOTION_CRON)
    status = _load_job_status()
    status["running"] = True
    _save_job_status(status)


def stop_limit_emotion_scheduler() -> None:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            logger.info("limit_emotion_scheduler stopped")
    status = _load_job_status()
    status["running"] = False
    status["stoppedAt"] = _beijing_now().isoformat(timespec="seconds")
    _save_job_status(status)


def get_limit_emotion_scheduler_status() -> dict[str, Any]:
    status = _load_job_status()
    status["running"] = _scheduler is not None
    return status


def run_limit_emotion_now() -> dict[str, Any]:
    with trigger_type("manual"):
        result = job_run_backfill()
    status = get_limit_emotion_scheduler_status()
    return {"ok": bool(result.get("ok")), "items": [status], "count": 1,
            "failed_count": 0 if result.get("ok") else 1}


def get_limit_emotion_scheduler() -> BackgroundScheduler | None:
    return _scheduler
