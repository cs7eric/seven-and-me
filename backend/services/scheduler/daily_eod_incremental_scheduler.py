"""每日 EOD 增量入 duckdb 调度器 (已废弃).

单 job:
  - 工作日 17:00 触发 (cron ``0 17 * * mon-fri``)
  - 调 ``scripts/daily_eod_incremental.py`` (所有步骤已拆分到独立 job, 脚本已空)

所有子步骤已拆分为独立 scheduler:
  - initial_backfill (16:45), qfq_reconciliation (16:50), limit_emotion (17:03),
    market_overview_daily (17:10), turnover_activity (17:12)

启动: :mod:`backend.bootstrap` 调 :func:`start_daily_eod_incremental_scheduler`.
关闭: ``MINIMAX_DAILY_EOD_INCREMENTAL_SCHEDULER_ENABLED=0``.
"""
from __future__ import annotations

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

from backend.services.scheduler.config_store import register_job
from backend.services.scheduler.status_store import load_status, save_status
from backend.services.stock.trading_calendar import is_trading_day
from backend.services.stock.trading_day_resolver import resolve_target_trading_day
from backend.services.scheduler.job_history import record_run, trigger_type

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


# ---------------------------------------------------------------------------
# Job 状态
# ---------------------------------------------------------------------------
def _job_default_status() -> dict[str, Any]:
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


def _load_job_status() -> dict[str, Any]:
    cfg = load_status("daily_eod_incremental")
    if not cfg:
        return _job_default_status()
    return cfg


def _save_job_status(status: dict[str, Any]) -> None:
    save_status("daily_eod_incremental", status)


# ---------------------------------------------------------------------------
# Jobs.json 注册
# ---------------------------------------------------------------------------
def _register_job(job_id: str, name: str, next_run_time: str | None) -> None:
    register_job(
        code="daily_eod_incremental",
        name=name,
        description=(
            "【已废弃】工作日 17:00 触发, 调 scripts/daily_eod_incremental.py, "
            "所有子步骤已拆分到独立 job: initial_backfill(16:45), qfq_reconciliation(16:50), "
            "limit_emotion(17:03), market_overview_daily(17:10), turnover_activity(17:12). "
            "保留 cron 仅做兜底."
        ),
        service_module="backend.services.scheduler.daily_eod_incremental_scheduler",
        service_class="DailyEodIncrementalScheduler",
        config_file="daily_eod_incremental_job.json",
        default_config=_job_default_status(),
    )


# ---------------------------------------------------------------------------
# Job 函数
# ---------------------------------------------------------------------------
def _job_run_incremental() -> None:
    """17:00 跑 daily_eod_incremental.py (subprocess, 不阻塞 scheduler).

    行为:
      - 今天 = 交易日 → 直接跑
      - 今天 ≠ 交易日 (周末/节假日) → 找最近一个交易日作为 target_date 跑
        (避免周五 cron 漏跑 / 节假日 cron 没触发, 周一 17:00 一并补齐)

    每次跑完 (不管成功失败 / script not found) 都写一条 history entry,
    供前端 /settings/scheduler 渲染"最近 50 次"列表.
    """
    now = _beijing_now()
    today = now.date()
    target_date = resolve_target_trading_day(today)

    status = _load_job_status()
    t0 = time.time()
    start_at_iso = now.isoformat(timespec="seconds")
    status["lastRunAt"] = start_at_iso
    if target_date != today:
        status["lastTargetTradeDate"] = target_date.isoformat()
        logger.info(
            "daily_eod_incremental: today=%s 非交易日, 改按 target=%s 跑",
            today, target_date,
        )
    else:
        status["lastTargetTradeDate"] = target_date.isoformat()

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
        record_run(
            _JOB_ID,
            status="failed",
            duration_seconds=status["lastDurationSeconds"],
            start_at=start_at_iso,
            end_at=datetime.now().isoformat(timespec="seconds"),
            error=msg,
        )
        return

    try:
        # 把 target_date 通过 env 传给子脚本, 避免它再用 date.today() 算出错的窗口
        script_env = {
            **os.environ,
            "MINIMAX_TARGET_TRADE_DATE": target_date.isoformat(),
        }
        r = subprocess.run(
            [sys.executable, "-u", str(script)],
            cwd=str(_repo_root()),
            check=False,
            capture_output=True,
            text=True,
            env=script_env,
            timeout=600,  # 10 分钟硬上限 (initial_backfill ~4 min + limit 50s + 余量)
        )
        elapsed = time.time() - t0
        status["lastDurationSeconds"] = round(elapsed, 1)
        if r.returncode == 0:
            status["lastRunOk"] = True
            status["lastRunError"] = None

            status["lastMessage"] = f"[{start_at_iso}]  ok"
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
    record_run(
        _JOB_ID,
        status="success" if status.get("lastRunOk") else "failed",
        duration_seconds=status.get("lastDurationSeconds"),
        start_at=start_at_iso,
        end_at=datetime.now().isoformat(timespec="seconds"),
        error=status.get("lastRunError"),
        message=status.get("lastMessage"),
    )


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
    """手动触发一次 (供 API 测试 / 前端按钮用). 标记 trigger=manual 进 history."""
    with trigger_type("manual"):
        _job_run_incremental()
    return get_daily_eod_incremental_scheduler_status()
