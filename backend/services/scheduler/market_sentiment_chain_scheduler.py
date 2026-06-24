from __future__ import annotations

import logging
import os
import threading
import time
import traceback
from datetime import datetime, timedelta
from typing import Any, Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.services.scheduler.config_store import register_job
from backend.services.scheduler.job_history import record_run, trigger_type
from backend.services.scheduler.status_store import load_status, save_status
from backend.services.scheduler.time_utils import cst_now_str
from backend.services.stock.trading_calendar import is_trading_day

from backend.services.scheduler.initial_backfill_scheduler import (
    _job_run_backfill as _run_initial_backfill,
    get_initial_backfill_scheduler_status,
)
from backend.services.scheduler.limit_emotion_scheduler import (
    _job_run_backfill as _run_limit_emotion,
    get_limit_emotion_scheduler_status,
)
from backend.services.scheduler.ma_count_scheduler import (
    _job_run_backfill as _run_ma_count,
    get_ma_count_scheduler_status,
)
from backend.services.scheduler.market_overview_daily_scheduler import (
    _job_run_backfill as _run_market_overview_daily,
    get_market_overview_daily_scheduler_status,
)
from backend.services.scheduler.market_sentiment_index_scheduler import (
    job_run_backfill as _run_market_sentiment_index,
    get_market_sentiment_index_scheduler_status,
)
from backend.services.scheduler.profit_effect_scheduler import (
    job_run_backfill as _run_profit_effect,
    get_profit_effect_scheduler_status,
)
from backend.services.scheduler.qfq_reconciliation_scheduler import (
    job_run_backfill as _run_qfq_reconciliation,
    get_qfq_reconciliation_scheduler_status,
)
from backend.services.scheduler.risk_appetite_scheduler import (
    _job_run_backfill as _run_risk_appetite,
    get_risk_appetite_scheduler_status,
)
from backend.services.scheduler.sector_breadth_scheduler import (
    job_run_backfill as _run_sector_breadth,
    get_sector_breadth_scheduler_status,
)
from backend.services.scheduler.style_risk_appetite_scheduler import (
    job_run_backfill as _run_style_risk_appetite,
    get_style_risk_appetite_scheduler_status,
)
from backend.services.scheduler.tdx_hsjday_download_scheduler import (
    _job_run_download as _run_tdx_hsjday_download,
    get_tdx_hsjday_download_scheduler_status,
)
from backend.services.scheduler.ths_industry_fund_flow_daily_scheduler import (
    _job_run_backfill as _run_ths_industry_fund_flow_daily,
    get_ths_industry_fund_flow_daily_scheduler_status,
)
from backend.services.scheduler.turnover_activity_scheduler import (
    job_run_backfill as _run_turnover_activity,
    get_turnover_activity_scheduler_status,
)
from backend.services.scheduler.volatility_sentiment_scheduler import (
    _job_run_backfill as _run_volatility_sentiment,
    get_volatility_sentiment_scheduler_status,
)

logger = logging.getLogger(__name__)

MARKET_SENTIMENT_CHAIN_CRON = "15 17 * * mon-fri"
_JOB_ID = "market_sentiment_chain_refresh"

_scheduler: BackgroundScheduler | None = None
_scheduler_lock = threading.Lock()


StepRunner = Callable[[], Any]
StepStatusGetter = Callable[[], dict[str, Any]]


_CHAIN_STEPS: list[tuple[str, StepRunner, StepStatusGetter]] = [
    ("tdx_hsjday_download", _run_tdx_hsjday_download, get_tdx_hsjday_download_scheduler_status),
    ("initial_backfill_refresh", _run_initial_backfill, get_initial_backfill_scheduler_status),
    ("qfq_reconciliation_refresh", _run_qfq_reconciliation, get_qfq_reconciliation_scheduler_status),
    ("limit_emotion_refresh", _run_limit_emotion, get_limit_emotion_scheduler_status),
    ("risk_appetite_refresh", _run_risk_appetite, get_risk_appetite_scheduler_status),
    ("ma_count_refresh", _run_ma_count, get_ma_count_scheduler_status),
    ("volatility_sentiment_refresh", _run_volatility_sentiment, get_volatility_sentiment_scheduler_status),
    ("style_risk_appetite_refresh", _run_style_risk_appetite, get_style_risk_appetite_scheduler_status),
    ("profit_effect_refresh", _run_profit_effect, get_profit_effect_scheduler_status),
    ("market_overview_daily", _run_market_overview_daily, get_market_overview_daily_scheduler_status),
    ("turnover_activity_refresh", _run_turnover_activity, get_turnover_activity_scheduler_status),
    ("ths_industry_fund_flow_daily", _run_ths_industry_fund_flow_daily, get_ths_industry_fund_flow_daily_scheduler_status),
    ("sector_breadth_refresh", _run_sector_breadth, get_sector_breadth_scheduler_status),
    ("market_sentiment_index_refresh", _run_market_sentiment_index, get_market_sentiment_index_scheduler_status),
]


def is_market_sentiment_chain_scheduler_enabled() -> bool:
    return os.environ.get("MINIMAX_MARKET_SENTIMENT_CHAIN_SCHEDULER_ENABLED", "1") != "0"


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _job_default_status() -> dict[str, Any]:
    return {
        "name": _JOB_ID,
        "lastRunAt": None,
        "lastRunOk": None,
        "lastStatus": None,
        "lastRunError": None,
        "lastDurationSeconds": None,
        "lastTargetsProcessed": None,
        "lastStep": None,
        "lastCompletedSteps": [],
        "totalRuns": 0,
        "totalFailures": 0,
        "schedulerStartedAt": None,
    }


def _load_job_status() -> dict[str, Any]:
    cfg = load_status(_JOB_ID)
    return cfg if cfg else _job_default_status()


def _save_job_status(status: dict[str, Any]) -> None:
    save_status(_JOB_ID, status)


def _register_job(job_id: str, name: str, next_run_time: str | None) -> None:
    register_job(
        code=job_id,
        name=name,
        description=(
            "工作日 17:15 串行执行 MSI 全链路: "
            "tdx_hsjday_download → initial_backfill → qfq_reconciliation → "
            "limit_emotion / risk_appetite / ma_count / volatility_sentiment / "
            "style_risk_appetite / profit_effect → market_overview_daily → "
            "turnover_activity → sector_breadth → market_sentiment_index。"
        ),
        service_module="backend.services.scheduler.market_sentiment_chain_scheduler",
        service_class="MarketSentimentChainScheduler",
        config_file="market_sentiment_chain_job.json",
        default_config=_job_default_status(),
        category_codes=["market_sentiment"],
        category_sort_orders={"market_sentiment": 5},
    )


def _is_step_success(status: dict[str, Any]) -> bool:
    if not isinstance(status, dict):
        return False
    last_status = str(status.get("lastStatus") or status.get("last_status") or "").strip().lower()
    if last_status:
        return last_status == "success"
    return bool(status.get("lastRunOk") if "lastRunOk" in status else status.get("last_run_ok"))


def _build_step_summary(step_code: str, step_status: dict[str, Any]) -> dict[str, Any]:
    return {
        "jobId": step_code,
        "ok": _is_step_success(step_status),
        "lastRunAt": step_status.get("lastRunAt") or step_status.get("last_run_at"),
        "lastStatus": step_status.get("lastStatus") or step_status.get("last_status"),
        "lastRunError": step_status.get("lastRunError") or step_status.get("last_error"),
        "lastMessage": step_status.get("lastMessage") or step_status.get("last_message"),
    }


def _job_run_chain() -> None:
    now = _beijing_now()
    start_at_iso = now.isoformat(timespec="seconds")
    status = _load_job_status()
    status["lastRunAt"] = start_at_iso
    status["lastStep"] = None
    status["lastCompletedSteps"] = []
    status["lastTargetsProcessed"] = 0
    _save_job_status(status)

    t0 = time.time()
    cst_time = cst_now_str()

    if not is_trading_day(now.date()):
        status["lastRunOk"] = True
        status["lastStatus"] = "skipped"
        status["lastRunError"] = f"{cst_time} 非交易日, 跳过串行 MSI 链路"
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        _save_job_status(status)
        record_run(
            _JOB_ID,
            status="skipped",
            duration_seconds=status.get("lastDurationSeconds"),
            start_at=start_at_iso,
            end_at=datetime.now().isoformat(timespec="seconds"),
            error=status.get("lastRunError"),
        )
        return

    completed_steps: list[str] = []
    step_results: list[dict[str, Any]] = []

    for step_code, runner, status_getter in _CHAIN_STEPS:
        status["lastStep"] = step_code
        _save_job_status(status)
        try:
            runner()
        except Exception as exc:
            status["lastRunOk"] = False
            status["lastStatus"] = "failed"
            status["lastRunError"] = f"{cst_time} {step_code} crashed: {type(exc).__name__}: {exc}"[:500]
            status["lastDurationSeconds"] = round(time.time() - t0, 1)
            status["lastCompletedSteps"] = completed_steps
            status["lastTargetsProcessed"] = len(completed_steps)
            status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
            _save_job_status(status)
            logger.warning(
                "market_sentiment_chain step crashed: %s\n%s",
                step_code,
                traceback.format_exc(),
            )
            record_run(
                _JOB_ID,
                status="failed",
                duration_seconds=status.get("lastDurationSeconds"),
                start_at=start_at_iso,
                end_at=datetime.now().isoformat(timespec="seconds"),
                error=status.get("lastRunError"),
            )
            return

        step_status = status_getter()
        summary = _build_step_summary(step_code, step_status)
        step_results.append(summary)
        if not summary["ok"]:
            status["lastRunOk"] = False
            status["lastStatus"] = "failed"
            status["lastRunError"] = (
                summary.get("lastRunError")
                or f"{cst_time} {step_code} failed"
            )
            status["lastDurationSeconds"] = round(time.time() - t0, 1)
            status["lastCompletedSteps"] = completed_steps
            status["lastTargetsProcessed"] = len(completed_steps)
            status["lastStepResults"] = step_results
            status["totalFailures"] = int(status.get("totalFailures") or 0) + 1
            _save_job_status(status)
            logger.warning(
                "market_sentiment_chain stopped at step=%s error=%s",
                step_code,
                status["lastRunError"],
            )
            record_run(
                _JOB_ID,
                status="failed",
                duration_seconds=status.get("lastDurationSeconds"),
                start_at=start_at_iso,
                end_at=datetime.now().isoformat(timespec="seconds"),
                error=str(status.get("lastRunError") or "")[:500],
                message=f"stopped_at={step_code}",
            )
            return

        completed_steps.append(step_code)
        status["lastCompletedSteps"] = completed_steps.copy()
        status["lastTargetsProcessed"] = len(completed_steps)
        status["lastStepResults"] = step_results.copy()
        _save_job_status(status)

    status["lastRunOk"] = True
    status["lastStatus"] = "success"
    status["lastRunError"] = None
    status["lastDurationSeconds"] = round(time.time() - t0, 1)
    status["lastCompletedSteps"] = completed_steps
    status["lastTargetsProcessed"] = len(completed_steps)
    status["lastStepResults"] = step_results
    status["lastMessage"] = f"completed {len(completed_steps)} MSI steps"
    status["totalRuns"] = int(status.get("totalRuns") or 0) + 1
    _save_job_status(status)
    logger.info("market_sentiment_chain ok in %.1fs: steps=%d", status["lastDurationSeconds"], len(completed_steps))
    record_run(
        _JOB_ID,
        status="success",
        duration_seconds=status.get("lastDurationSeconds"),
        start_at=start_at_iso,
        end_at=datetime.now().isoformat(timespec="seconds"),
        message=status.get("lastMessage"),
    )


def start_market_sentiment_chain_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    with _scheduler_lock:
        if _scheduler is not None:
            return
        status = _load_job_status()
        if not status.get("enabled", True):
            logger.info("[MarketSentimentChainScheduler] disabled by config, not started")
            return

        sched = BackgroundScheduler(timezone="Asia/Shanghai")
        sched.add_job(
            _job_run_chain,
            CronTrigger.from_crontab(MARKET_SENTIMENT_CHAIN_CRON),
            id=_JOB_ID,
            max_instances=1,
            coalesce=True,
        )
        sched.start()
        _scheduler = sched

        status["schedulerStartedAt"] = _beijing_now().isoformat(timespec="seconds")
        _register_job(
            _JOB_ID,
            "market_sentiment_chain_refresh (17:15 工作日, 串行 MSI 全链路)",
            None,
        )
        _save_job_status(status)
        logger.info("market_sentiment_chain_scheduler started: cron=%s", MARKET_SENTIMENT_CHAIN_CRON)

    status = _load_job_status()
    status["running"] = True
    status["schedulerStartedAt"] = _beijing_now().isoformat(timespec="seconds")
    _save_job_status(status)


def stop_market_sentiment_chain_scheduler() -> None:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            logger.info("market_sentiment_chain_scheduler stopped")

    status = _load_job_status()
    status["running"] = False
    status["stoppedAt"] = _beijing_now().isoformat(timespec="seconds")
    _save_job_status(status)


def get_market_sentiment_chain_scheduler_status() -> dict[str, Any]:
    status = _load_job_status()
    status["running"] = _scheduler is not None
    return status


def run_market_sentiment_chain_now() -> dict[str, Any]:
    with trigger_type("manual"):
        _job_run_chain()
    status = get_market_sentiment_chain_scheduler_status()
    return {
        "ok": bool(status.get("lastRunOk")),
        "items": [status],
        "count": 1,
        "failed_count": 0 if status.get("lastRunOk") else 1,
    }
