r"""同花顺 90 行业资金流 Postgres 日度快照 scheduler.

维护前请先看:
`F:\dev-repo\mp4-to-word-new\design\backend\industry-concept-fund-flow-postgres-migration.md`

单 job:
  - 工作日 17:15 触发 (cron ``15 17 * * mon-fri``, is_trading_day 二次过滤)
  - 直接爬同花顺资金流页面
  - 爬完立刻按交易日写入 Postgres `app.sector_fund_flow_*`
  - 幂等: 同交易日旧 alive 快照先软删, 再写新快照

跟 market_overview_daily (17:10) 关系:
  - 17:10 大盘 / 行业 (akshare 源, market_pulse_sector_daily)
  - 17:15 同花顺 90 行业资金流 (hexin-v 源, ths_industry_fund_flow_daily)
  两表数据源不同 (akshare vs 同花顺 hexin-v), 口径可能略不同, **并存**不覆盖.

启动: :mod:`backend.bootstrap` 调 :func:`start_ths_industry_fund_flow_daily_scheduler`.
关闭: ``MINIMAX_THS_INDUSTRY_FUND_FLOW_DAILY_SCHEDULER_ENABLED=0``.

状态文件: ``F:\\dev-repo\\mp4-to-word-new\\scheduler\\ths_industry_fund_flow_daily_job.json``
Jobs 注册表: ``F:\\dev-repo\\mp4-to-word-new\\scheduler\\jobs.json``
"""
from __future__ import annotations

import logging
import os
import threading
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.services.stock.trading_calendar import is_trading_day
from backend.services.scheduler.job_history import record_run, trigger_type
from backend.services.stock.trading_day_resolver import resolve_target_trading_day
from backend.services.scheduler.config_store import register_job
from backend.services.scheduler.status_store import load_status, save_status
from backend.services.scheduler.time_utils import cst_now_str

logger = logging.getLogger(__name__)

FF_DAILY_CRON = "15 17 * * mon-fri"  # 工作日 17:15 (北京时间, 跟 17:10 market_overview_daily 错开)
_JOB_ID = "ths_industry_fund_flow_daily"
_scheduler: BackgroundScheduler | None = None
_scheduler_lock = threading.Lock()


def is_ths_industry_fund_flow_daily_scheduler_enabled() -> bool:
    return os.environ.get("MINIMAX_THS_INDUSTRY_FUND_FLOW_DAILY_SCHEDULER_ENABLED", "1") != "0"


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Job 状态
# ---------------------------------------------------------------------------
def _job_default_status() -> dict[str, Any]:
    return {
        "name": _JOB_ID,
        "lastRunAt": None,
        "lastRunOk": None,
        "lastRunError": None,
        "lastDurationSeconds": None,
        "lastDaysRequested": None,
        "lastDaysUpserted": None,
        "lastRowsUpserted": None,
        "lastCoverage": None,
        "totalRuns": 0,
        "totalFailures": 0,
        "schedulerStartedAt": None,
    }


def _load_job_status() -> dict[str, Any]:
    cfg = load_status("ths_industry_fund_flow_daily")
    if not cfg:
        return _job_default_status()
    return cfg


def _save_job_status(status: dict[str, Any]) -> None:
    save_status("ths_industry_fund_flow_daily", status)


# ---------------------------------------------------------------------------
# Jobs.json 注册
# ---------------------------------------------------------------------------
def _register_job(job_id: str, name: str, next_run_time: str | None) -> None:
    register_job(
        code=job_id,
        name=name,
        description=(
            "工作日 17:15 触发, 直接爬同花顺行业资金流页面并按交易日写入 "
            "Postgres app.sector_fund_flow_capture_batches / app.sector_fund_flow_daily_snapshots。"
            "同交易日旧 alive 快照先软删再写新快照, 供 Industry / Concept Application "
            "资金流页与历史序列接口复用。"
        ),
        service_module="backend.services.scheduler.ths_industry_fund_flow_daily_scheduler",
        service_class="ThsIndustryFundFlowDailyScheduler",
        config_file="ths_industry_fund_flow_daily_job.json",
        default_config=_job_default_status(),
    )


# ---------------------------------------------------------------------------
# stdout 解析
# ---------------------------------------------------------------------------
def _job_run_backfill() -> None:
    """17:15 抓取行业资金流并直接写 Postgres 交易日快照."""
    now = _beijing_now()
    today = now.date()
    target_date = resolve_target_trading_day(today)

    status = _load_job_status()
    t0 = time.time()
    status["lastRunAt"] = now.isoformat(timespec="seconds")
    start_at_iso = now.isoformat(timespec="seconds")
    cst_time = cst_now_str()
    if target_date != today:
        status["lastTargetTradeDate"] = target_date.isoformat()
        logger.info(
            "ths_industry_fund_flow_daily: today=%s 非交易日, 改按 target=%s 跑",
            today, target_date,
        )
    else:
        status["lastTargetTradeDate"] = target_date.isoformat()

    try:
        from backend.config.database import session_scope
        from backend.services.stock.f10.ths_fund_flow_service import ThsIndustryFundFlowService

        with session_scope() as db:
            payload = ThsIndustryFundFlowService(db).refresh_industry_fund_flow(
                trade_date=target_date,
            )
            coverage = ThsIndustryFundFlowService(db).repo.coverage()
        elapsed = time.time() - t0
        status["lastDurationSeconds"] = round(elapsed, 1)
        status["lastDaysRequested"] = 1
        status["lastDaysUpserted"] = 1 if payload.get("rowCount") else 0
        status["lastRowsUpserted"] = int(payload.get("rowCount") or 0)
        status["lastRunOk"] = True
        status["lastRunError"] = None
        status["lastMessage"] = (
            f"trade_date={target_date.isoformat()} rows={status.get('lastRowsUpserted', 0)}"
        )
        status["lastCoverage"] = coverage
        status["totalRuns"] = int(status.get("totalRuns") or 0) + 1
        logger.info(
            "ths_industry_fund_flow_daily ok in %.1fs: trade_date=%s rows=%s",
            elapsed,
            target_date.isoformat(),
            status.get("lastRowsUpserted"),
        )
    except Exception as exc:
        status["lastRunOk"] = False
        status["lastRunError"] = f"{type(exc).__name__}: {exc}"[:300]
        status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        logger.warning(
            "ths_industry_fund_flow_daily crashed: %s\n%s", exc, traceback.format_exc()
        )

    _save_job_status(status)

    record_run(
        "ths_industry_fund_flow_daily",
        status="success" if status.get("lastRunOk") else "failed",
        duration_seconds=status.get("lastDurationSeconds"),
        start_at=start_at_iso,
        end_at=datetime.now().isoformat(timespec="seconds"),
        error=status.get("lastRunError"),
        message=status.get("lastMessage"),
    )
# ---------------------------------------------------------------------------
# 启动 / 停止 / 状态 / 手动触发
# ---------------------------------------------------------------------------
def start_ths_industry_fund_flow_daily_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    with _scheduler_lock:
        if _scheduler is not None:
            return
        status = _load_job_status()
        if not status.get("enabled", True):
            logger.info(
                "[ThsIndustryFundFlowDailyScheduler] disabled by config, not started"
            )
            return

        sched = BackgroundScheduler(timezone="Asia/Shanghai")
        sched.add_job(
            _job_run_backfill,
            CronTrigger.from_crontab(FF_DAILY_CRON),
            id=_JOB_ID,
            max_instances=1,
            coalesce=True,
        )
        sched.start()
        _scheduler = sched

        status["schedulerStartedAt"] = _beijing_now().isoformat(timespec="seconds")
        _register_job(
            _JOB_ID,
            "ths_industry_fund_flow_daily (17:15 工作日, 同花顺 90 行业资金流 → Postgres)",
            None,
            )
        _save_job_status(status)
        logger.info(
            "ths_industry_fund_flow_daily_scheduler started: cron=%s (workday only via is_trading_day)",
            FF_DAILY_CRON,
        )

    status = _load_job_status()
    status["running"] = True
    _save_job_status(status)


def stop_ths_industry_fund_flow_daily_scheduler() -> None:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            logger.info("ths_industry_fund_flow_daily_scheduler stopped")

    status = _load_job_status()
    status["running"] = False
    status["stoppedAt"] = _beijing_now().isoformat(timespec="seconds")
    _save_job_status(status)

    


def get_ths_industry_fund_flow_daily_scheduler_status() -> dict[str, Any]:
    status = _load_job_status()
    status["running"] = _scheduler is not None
    return status


def run_ths_industry_fund_flow_daily_now() -> dict[str, Any]:
    """手动触发一次 (供 API 测试 / 前端按钮用). 标记 trigger=manual 进 history."""
    with trigger_type("manual"):
        _job_run_backfill()
    status = get_ths_industry_fund_flow_daily_scheduler_status()
    return {
        "ok": bool(status.get("lastRunOk")),
        "items": [status],
        "count": 1,
        "failed_count": 0 if status.get("lastRunOk") else 1,
    }
