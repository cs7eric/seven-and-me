"""QFQ/HFQ 复权对账 scheduler.

单 job:
  - 工作日 17:30 触发 (cron ``30 17 * * mon-fri``)
  - 调 ``scripts/fetch_one_date_eltdx.py`` 补拉 qfq/hfq 复权数据

校验: subprocess 成功后, 检查 daily_qfq 在目标日至少有 100 行.

启动: :mod:`backend.bootstrap` 调 :func:`start_qfq_reconciliation_scheduler`.
关闭: ``MINIMAX_QFQ_RECONCILIATION_SCHEDULER_ENABLED=0``.
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
from backend.services.scheduler.target_date import resolve_scheduler_target_date

logger = logging.getLogger(__name__)

QFQ_RECON_CRON = "30 17 * * mon-fri"
_JOB_ID = "qfq_reconciliation_refresh"
_SCRIPT_PATH_KEY = "qfq_reconciliation_script"
_JOB_TIMEOUT_SECONDS = 10 * 60

_scheduler: BackgroundScheduler | None = None
_scheduler_lock = threading.Lock()


def is_qfq_reconciliation_scheduler_enabled() -> bool:
    return os.environ.get("MINIMAX_QFQ_RECONCILIATION_SCHEDULER_ENABLED", "1") != "0"


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_script_path() -> str:
    return str(_repo_root() / "scripts" / "fetch_one_date_eltdx.py")


def _job_default_status() -> dict[str, Any]:
    return {
        "name": _JOB_ID,
        "lastRunAt": None, "lastRunOk": None, "lastRunError": None,
        "lastDurationSeconds": None, "last_qfq_rows": None, "last_hfq_rows": None, "last_errors": None,
        "totalRuns": 0, "totalFailures": 0, "schedulerStartedAt": None,
    }


def _load_job_status() -> dict[str, Any]:
    cfg = load_status("qfq_reconciliation_refresh")
    return cfg if cfg else _job_default_status()


def _save_job_status(status: dict[str, Any]) -> None:
    save_status("qfq_reconciliation_refresh", status)


def _register_job(job_id: str, name: str, next_run_time: str | None) -> None:
    register_job(
        code="qfq_reconciliation_refresh", name=name,
        description=(
            "MSI 上游: qfq/hfq 复权数据对账补拉. "
            "工作日 16:50 触发, 调 scripts/fetch_one_date_eltdx.py, "
            "找 daily_raw 有但 daily_qfq/daily_hfq 缺的 trade_date 逐日补拉. "
            "依赖 initial_backfill 16:45 必须先落 daily_raw."
        ),
        service_module="backend.services.scheduler.qfq_reconciliation_scheduler",
        service_class="QfqReconciliationScheduler",
        config_file="qfq_reconciliation_job.json",
        default_config=_job_default_status(),
    )


def job_run_backfill(target_date=None) -> dict:
    now = _beijing_now()
    target_date = resolve_scheduler_target_date(now.date(), target_date)
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
        logger.error("qfq_reconciliation: %s", msg)
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
            [sys.executable, "-u", str(script), "--adjust=both", "--workers=32",
             "--date={}".format(target_date.isoformat())],
            cwd=str(_repo_root()), check=False, capture_output=True, text=True,
            env=script_env, timeout=_JOB_TIMEOUT_SECONDS,
        )
        elapsed = time.time() - t0
        status["lastDurationSeconds"] = round(elapsed, 1)

        stdout = (r.stdout or "") + "\n" + (r.stderr or "")
        for key in ["qfq_rows", "hfq_rows", "errors"]:
            m = re.search(r"{}[=:]\s*(\d+)".format(key), stdout)
            if m:
                status["last_" + key] = int(m.group(1))

        if r.returncode == 0:
            # DuckDB 数据校验: daily_qfq + daily_hfq 两表都有数据
            _valid_q, _err_q = validate_count("daily_qfq", target_date, min_rows=1000)
            _valid_h, _err_h = validate_count("daily_hfq", target_date, min_rows=1000)
            if not _valid_q:
                status["lastRunOk"] = False
                status["lastRunError"] = f"{cst_time} " + "[校验失败] daily_qfq: " + str(_err_q)
                status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
                logger.warning("qfq_reconciliation validation failed in %.1fs: %s", elapsed, _err_q)
            elif not _valid_h:
                status["lastRunOk"] = False
                status["lastRunError"] = f"{cst_time} " + "[校验失败] daily_hfq: " + str(_err_h)
                status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
                logger.warning("qfq_reconciliation hfq validation failed in %.1fs: %s", elapsed, _err_h)
            else:
                status["lastRunOk"] = True
                status["lastRunError"] = None

                status["lastMessage"] = f"{cst_time}  ok, qfq={status.get('last_qfq_rows','?')} hfq={status.get('last_hfq_rows','?')} rows"
                status["totalRuns"] = int(status.get("totalRuns") or 0) + 1
                logger.info("qfq_reconciliation ok in %.1fs: qfq=%s hfq=%s err=%s",
                            elapsed, status.get("last_qfq_rows"), status.get("last_hfq_rows"),
                            status.get("last_errors"))
        else:
            err_tail = (r.stderr or r.stdout or "")[-500:].strip()
            status["lastRunOk"] = False
            status["lastRunError"] = f"{cst_time} " + str(err_tail or "exit={}".format(r.returncode))
            status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
            logger.warning("qfq_reconciliation failed in %.1fs: exit=%d\n%s", elapsed, r.returncode, err_tail)
    except subprocess.TimeoutExpired:
        status["lastRunOk"] = False
        status["lastRunError"] = f"{cst_time} " + "timeout (>{}s)".format(_JOB_TIMEOUT_SECONDS)
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning("qfq_reconciliation timeout after %.1fs", time.time() - t0)
    except Exception as exc:
        status["lastRunOk"] = False
        status["lastRunError"] = f"{cst_time} " + "{}: {}".format(type(exc).__name__, exc)[:300]
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning("qfq_reconciliation crashed: %s\n%s", exc, traceback.format_exc())

    _save_job_status(status)
    record_run(_JOB_ID, status="success" if status.get("lastRunOk") else "failed",
               duration_seconds=status.get("lastDurationSeconds"),
               start_at=start_at_iso, end_at=datetime.now().isoformat(timespec="seconds"),
               error=status.get("lastRunError"),
               message=status.get("lastMessage"))
    return {"ok": bool(status.get("lastRunOk"))}


def _job_run_backfill() -> None:
    job_run_backfill()


def start_qfq_reconciliation_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    with _scheduler_lock:
        if _scheduler is not None:
            return
        status = _load_job_status()
        if not status.get("enabled", True):
            logger.info("[QfqReconciliationScheduler] disabled by config, not started")
            return
        sched = BackgroundScheduler(timezone="Asia/Shanghai")
        sched.add_job(_job_run_backfill, CronTrigger.from_crontab(QFQ_RECON_CRON),
                       id=_JOB_ID, max_instances=1, coalesce=True)
        sched.start()
        _scheduler = sched
        status["schedulerStartedAt"] = _beijing_now().isoformat(timespec="seconds")
        _register_job(_JOB_ID, "qfq_reconciliation_refresh (16:50, qfq/hfq 对账补拉)", None)
        _save_job_status(status)
        logger.info("qfq_reconciliation_scheduler started: cron=%s", QFQ_RECON_CRON)
    status = _load_job_status()
    status["running"] = True
    _save_job_status(status)


def stop_qfq_reconciliation_scheduler() -> None:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            logger.info("qfq_reconciliation_scheduler stopped")
    status = _load_job_status()
    status["running"] = False
    status["stoppedAt"] = _beijing_now().isoformat(timespec="seconds")
    _save_job_status(status)


def get_qfq_reconciliation_scheduler_status() -> dict[str, Any]:
    status = _load_job_status()
    status["running"] = _scheduler is not None
    return status


def run_qfq_reconciliation_now(target_date=None) -> dict[str, Any]:
    with trigger_type("manual"):
        result = job_run_backfill(target_date=target_date)
    status = get_qfq_reconciliation_scheduler_status()
    return {"ok": bool(result.get("ok")), "items": [status], "count": 1,
            "failed_count": 0 if result.get("ok") else 1}


def get_qfq_reconciliation_scheduler() -> BackgroundScheduler | None:
    return _scheduler
