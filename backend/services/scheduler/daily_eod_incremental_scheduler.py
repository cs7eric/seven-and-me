"""每日 EOD 增量入 duckdb 调度器.

单 job:
  - 工作日 17:00 触发 (cron ``0 17 * * mon-fri``, 同时 ``is_trading_day`` 二次过滤节假日)
  - 调 ``scripts/daily_eod_incremental.py`` 跑两步:
    1. 查 duckdb daily_raw.max(trade_date) vs today, 缺则跑 ``initial_backfill.py``
    2. 调 ``backfill_limit_emotion_summary.py`` 回算 limit_emotion_summary_daily

启动: :mod:`backend.bootstrap` 调 :func:`start_daily_eod_incremental_scheduler`.
关闭: ``MINIMAX_DAILY_EOD_INCREMENTAL_SCHEDULER_ENABLED=0``.

状态文件: ``F:\\dev-repo\\mp4-to-word-new\\scheduler\\daily_eod_incremental_job.json``
Jobs 注册表: ``F:\\dev-repo\\mp4-to-word-new\\scheduler\\jobs.json``
"""
from __future__ import annotations

import json
import logging
import os
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

from backend.config.settings import (
    SCHEDULER_DIR,
    SCHEDULER_JOBS_FILE,
)
from backend.services.stock.trading_calendar import is_trading_day
from backend.utils.json_io import read_json_file

logger = logging.getLogger(__name__)

DAILY_EOD_CRON = "0 17 * * mon-fri"  # 工作日 17:00 (北京时间)
_JOB_ID = "daily_eod_incremental"
_STATUS_FILE_NAME = "daily_eod_incremental_job.json"
_SCRIPT_PATH_KEY = "daily_eod_incremental_script"  # 状态文件里可覆盖脚本路径 (测试用)

_scheduler: BackgroundScheduler | None = None
_scheduler_lock = threading.Lock()


def is_daily_eod_incremental_scheduler_enabled() -> bool:
    return os.environ.get("MINIMAX_DAILY_EOD_INCREMENTAL_SCHEDULER_ENABLED", "1") != "0"


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _status_file() -> Path:
    return SCHEDULER_DIR / _STATUS_FILE_NAME


# ---------------------------------------------------------------------------
# Job 状态
# ---------------------------------------------------------------------------
def _load_job_status() -> dict[str, Any]:
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    if not _status_file().exists():
        return {
            "name": _JOB_ID,
            "lastRunAt": None,
            "lastRunOk": None,
            "lastRunError": None,
            "lastMaxTradeDate": None,
            "lastLimitEmotionMaxDate": None,
            "lastBackfillOk": None,
            "lastSummaryOk": None,
            "lastDurationSeconds": None,
            "totalRuns": 0,
            "totalFailures": 0,
            "schedulerStartedAt": None,
        }
    try:
        return json.loads(_status_file().read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("daily_eod_incremental job status read failed: %s", exc)
        return {}


def _save_job_status(status: dict[str, Any]) -> None:
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _status_file().with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    tmp.replace(_status_file())


# ---------------------------------------------------------------------------
# Jobs.json 注册
# ---------------------------------------------------------------------------
def _register_job(job_id: str, name: str, next_run_time: str | None) -> None:
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    if SCHEDULER_JOBS_FILE.exists():
        data = read_json_file(SCHEDULER_JOBS_FILE, {"version": 1, "jobs": []})
    else:
        data = {"version": 1, "jobs": []}
    if isinstance(data, list):
        data = {"version": 1, "jobs": data}
    if not isinstance(data, dict):
        data = {"version": 1, "jobs": []}
    jobs = data.setdefault("jobs", [])
    jobs = [j for j in jobs if j.get("id") != job_id]
    now_iso = _beijing_now().isoformat(timespec="seconds")
    payload = {
        "id": job_id,
        "name": name,
        "description": (
            "工作日 17:00 触发, 调 scripts/daily_eod_incremental.py, "
            "查 duckdb daily_raw.max(trade_date) vs today, 缺则跑 initial_backfill.py 补全, "
            "然后回算 limit_emotion_summary_daily 涨跌停综合分; 周末 / 节假日由 is_trading_day 二次过滤"
        ),
        "config_file": _STATUS_FILE_NAME,
        "service_module": "backend.services.scheduler.daily_eod_incremental_scheduler",
        "service_class": "DailyEodIncrementalScheduler",
        "enabled": True,
        "registered_at": now_iso,
        "module": "backend.services.scheduler.daily_eod_incremental_scheduler",
        "nextRunTime": next_run_time,
        "updatedAt": now_iso,
    }
    jobs.append(payload)
    from backend.utils.json_io import write_json_file
    write_json_file(SCHEDULER_JOBS_FILE, data)


# ---------------------------------------------------------------------------
# Job 函数
# ---------------------------------------------------------------------------
def _job_run_incremental() -> None:
    """17:00 跑 daily_eod_incremental.py (subprocess, 不阻塞 scheduler)."""
    now = _beijing_now()
    if not is_trading_day(now.date()):
        logger.info("daily_eod_incremental skipped: %s not trading day", now.date())
        return

    status = _load_job_status()
    t0 = time.time()
    status["lastRunAt"] = now.isoformat(timespec="seconds")

    # 脚本路径: 状态文件可覆盖 (测试用), 默认走 repo root
    script_path = status.get(_SCRIPT_PATH_KEY) or _default_script_path()
    script = Path(script_path)
    if not script.is_absolute():
        script = _repo_root() / script
    if not script.exists():
        msg = f"script not found: {script}"
        logger.error("daily_eod_incremental: %s", msg)
        status["lastRunOk"] = False
        status["lastRunError"] = msg
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        _save_job_status(status)
        return

    try:
        r = subprocess.run(
            [sys.executable, "-u", str(script)],
            cwd=str(_repo_root()),
            check=False,
            capture_output=True,
            text=True,
            timeout=600,  # 10 分钟硬上限 (initial_backfill ~4 min + limit 50s + 余量)
        )
        elapsed = time.time() - t0
        status["lastDurationSeconds"] = round(elapsed, 1)
        if r.returncode == 0:
            status["lastRunOk"] = True
            status["lastRunError"] = None
            status["totalRuns"] = int(status.get("totalRuns") or 0) + 1
            logger.info(
                "daily_eod_incremental ok in %.1fs (stdout=%d lines)",
                elapsed, len(r.stdout.splitlines()),
            )
            # 跑成功后, 重新读一次 duckdb max 日期写进状态 (前端展示用)
            _refresh_max_dates(status)
        else:
            status["lastRunOk"] = False
            err_tail = (r.stderr or r.stdout or "")[-300:].strip()
            status["lastRunError"] = err_tail or f"exit={r.returncode}"
            status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
            logger.warning(
                "daily_eod_incremental failed in %.1fs: exit=%d\n%s",
                elapsed, r.returncode, err_tail,
            )
    except subprocess.TimeoutExpired:
        status["lastRunOk"] = False
        status["lastRunError"] = "timeout (>600s)"
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning("daily_eod_incremental timeout after %.1fs", time.time() - t0)
    except Exception as exc:
        status["lastRunOk"] = False
        status["lastRunError"] = f"{type(exc).__name__}: {exc}"[:300]
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning(
            "daily_eod_incremental crashed: %s\n%s", exc, traceback.format_exc()
        )

    _save_job_status(status)


def _refresh_max_dates(status: dict[str, Any]) -> None:
    """从 duckdb 读 max(daily_raw.trade_date) 和 max(limit_emotion.trade_date) 写进 status."""
    try:
        from backend.adapters.market.duckdb_store import get_conn
        with get_conn() as c:
            r1 = c.execute("SELECT MAX(trade_date) FROM daily_raw").fetchone()
            r2 = c.execute(
                "SELECT MAX(trade_date) FROM limit_emotion_summary_daily"
            ).fetchone()
        if r1 and r1[0] is not None:
            v = r1[0]
            status["lastMaxTradeDate"] = v.date().isoformat() if hasattr(v, "date") else str(v)
        if r2 and r2[0] is not None:
            v = r2[0]
            status["lastLimitEmotionMaxDate"] = (
                v.date().isoformat() if hasattr(v, "date") else str(v)
            )
    except Exception as exc:
        logger.debug("refresh_max_dates failed: %s", exc)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_script_path() -> str:
    return str(_repo_root() / "scripts" / "daily_eod_incremental.py")


# ---------------------------------------------------------------------------
# 启动 / 停止 / 状态
# ---------------------------------------------------------------------------
def start_daily_eod_incremental_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    with _scheduler_lock:
        if _scheduler is not None:
            return
        status = _load_job_status()
        if not status.get("enabled", True):
            logger.info(
                "[DailyEodIncrementalScheduler] disabled by config (%s enabled=false), not started",
                _STATUS_FILE_NAME,
            )
            return

        sched = BackgroundScheduler(timezone="Asia/Shanghai")
        sched.add_job(
            _job_run_incremental,
            CronTrigger.from_crontab(DAILY_EOD_CRON),
            id=_JOB_ID,
            max_instances=1,
            coalesce=True,
        )
        sched.start()
        _scheduler = sched

        status["schedulerStartedAt"] = _beijing_now().isoformat(timespec="seconds")
        _save_job_status(status)
        _register_job(
            _JOB_ID,
            "daily_eod_incremental (17:00 工作日, 入 duckdb + 回算 limit 综合分)",
            None,
        )
        logger.info(
            "daily_eod_incremental_scheduler started: cron=%s (workday only via is_trading_day)",
            DAILY_EOD_CRON,
        )

    status = _load_job_status()
    status["running"] = True
    status["schedulerStartedAt"] = _beijing_now().isoformat(timespec="seconds")
    _save_job_status(status)


def stop_daily_eod_incremental_scheduler() -> None:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            logger.info("daily_eod_incremental_scheduler stopped")

    status = _load_job_status()
    status["running"] = False
    status["stoppedAt"] = _beijing_now().isoformat(timespec="seconds")
    _save_job_status(status)


def get_daily_eod_incremental_scheduler_status() -> dict[str, Any]:
    status = _load_job_status()
    status["running"] = _scheduler is not None
    return status


def run_daily_eod_incremental_now() -> dict[str, Any]:
    """手动触发一次 (供 API 测试 / 前端按钮用)."""
    _job_run_incremental()
    return get_daily_eod_incremental_scheduler_status()
