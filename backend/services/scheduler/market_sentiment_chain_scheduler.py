from __future__ import annotations

import logging
import os
import threading
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.services.scheduler.config_store import register_job
from backend.services.scheduler.job_history import (
    begin_run,
    mark_processing_interrupted,
    record_run,
    trigger_type,
    update_run,
)
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
_run_lock = threading.Lock()
_CHAIN_LOCK_PATH = Path(__file__).resolve().parents[3] / "runtime" / "market_sentiment_chain_refresh.lock"
_CHAIN_CHECKPOINT_PATH = Path(__file__).resolve().parents[3] / "runtime" / "market_sentiment_chain_refresh.checkpoint.json"


StepRunner = Callable[..., Any]
StepStatusGetter = Callable[[], dict[str, Any]]


class _ChainProcessLock:
    def __init__(self) -> None:
        self._fh = None

    def acquire(self) -> bool:
        _CHAIN_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(2):
            fh = open(_CHAIN_LOCK_PATH, "a+b")
            fh.seek(0, os.SEEK_END)
            if fh.tell() == 0:
                fh.write(b"0")
                fh.flush()
            fh.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                fh.close()
                if attempt == 0:
                    # Lock may be stale from a killed process — remove and retry
                    try:
                        _CHAIN_LOCK_PATH.unlink(missing_ok=True)
                    except OSError:
                        pass
                    continue
                return False
            self._fh = fh
            return True
        return False

    def release(self) -> None:
        fh = self._fh
        self._fh = None
        if fh is None:
            return
        try:
            fh.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


def _save_checkpoint(target_date: Any, completed_steps: list[str]) -> None:
    """Save checkpoint so the chain can resume after a restart."""
    try:
        _CHAIN_CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        import json as _json

        data = {
            "target_date": target_date.isoformat() if hasattr(target_date, "isoformat") else target_date,
            "completed_steps": completed_steps,
            "saved_at": _beijing_now().isoformat(timespec="seconds"),
        }
        tmp = _CHAIN_CHECKPOINT_PATH.with_suffix(".tmp")
        tmp.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_CHAIN_CHECKPOINT_PATH)
    except Exception:
        logger.warning("Failed to save chain checkpoint", exc_info=True)


def _load_checkpoint() -> dict[str, Any] | None:
    """Load checkpoint if one exists. Returns None if no valid checkpoint."""
    try:
        if not _CHAIN_CHECKPOINT_PATH.exists():
            return None
        import json as _json

        data = _json.loads(_CHAIN_CHECKPOINT_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "completed_steps" not in data:
            return None
        return data
    except Exception:
        return None


def _clear_checkpoint() -> None:
    """Remove checkpoint file after chain completes or fails."""
    try:
        if _CHAIN_CHECKPOINT_PATH.exists():
            _CHAIN_CHECKPOINT_PATH.unlink()
    except Exception:
        pass


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
    last_run_ok = bool(status.get("lastRunOk") if "lastRunOk" in status else status.get("last_run_ok"))
    if last_status:
        if last_status == "success":
            return True
        if last_status.startswith("skipped"):
            return last_run_ok
        return False
    return last_run_ok


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    return value


def _build_step_summary(step_code: str, step_status: dict[str, Any]) -> dict[str, Any]:
    return _json_safe({
        "jobId": step_code,
        "ok": _is_step_success(step_status),
        "lastRunAt": step_status.get("lastRunAt") or step_status.get("last_run_at"),
        "lastStatus": step_status.get("lastStatus") or step_status.get("last_status"),
        "lastRunError": step_status.get("lastRunError") or step_status.get("last_error"),
        "lastMessage": step_status.get("lastMessage") or step_status.get("last_message"),
    })


def _record_already_running() -> None:
    now = _beijing_now()
    start_at_iso = now.isoformat(timespec="seconds")
    cst_time = cst_now_str()
    status = _load_job_status()
    status["lastRunAt"] = start_at_iso
    status["lastRunOk"] = True
    status["lastStatus"] = "skipped"
    status["lastRunError"] = f"{cst_time} market_sentiment_chain 已有执行中, 本次触发跳过"
    status["lastDurationSeconds"] = 0.0
    status["lastMessage"] = status["lastRunError"]
    _save_job_status(status)
    logger.warning("market_sentiment_chain trigger skipped: already running")


def _job_run_chain_unlocked(target_date=None) -> None:
    now = _beijing_now()
    start_at_iso = now.isoformat(timespec="seconds")
    history_id = begin_run(
        _JOB_ID,
        start_at=start_at_iso,
        message="market_sentiment_chain processing",
    )

    def _finish_history(
        *,
        final_status: str,
        duration_seconds: float | None,
        error: str | None = None,
        message: str | None = None,
    ) -> None:
        updated = update_run(
            history_id,
            status=final_status,  # type: ignore[arg-type]
            duration_seconds=duration_seconds,
            end_at=_beijing_now().isoformat(timespec="seconds"),
            error=error,
            message=message,
        )
        if updated is None:
            record_run(
                _JOB_ID,
                status=final_status,  # type: ignore[arg-type]
                duration_seconds=duration_seconds,
                start_at=start_at_iso,
                end_at=_beijing_now().isoformat(timespec="seconds"),
                error=error,
                message=message,
            )

    status = _load_job_status()

    # --- Checkpoint / Resume ---
    checkpoint = _load_checkpoint()
    if checkpoint and checkpoint.get("completed_steps"):
        # Resuming from a previous interrupted run
        completed_steps: list[str] = list(checkpoint["completed_steps"])
        if target_date is None and checkpoint.get("target_date"):
            target_date = checkpoint["target_date"]
        step_results: list[dict[str, Any]] = []
        # Rebuild step_results from sub-step statuses for already-completed steps
        step_code_to_getter = {code: getter for code, _, getter in _CHAIN_STEPS}
        for code in completed_steps:
            getter = step_code_to_getter.get(code)
            if getter:
                step_results.append(_build_step_summary(code, getter()))
        remaining_steps = [
            (code, runner, getter)
            for code, runner, getter in _CHAIN_STEPS
            if code not in set(completed_steps)
        ]
        logger.info(
            "market_sentiment_chain resuming from checkpoint: %d done, %d remaining",
            len(completed_steps), len(remaining_steps),
        )
    else:
        completed_steps = []
        step_results = []
        remaining_steps = list(_CHAIN_STEPS)

    status["lastRunAt"] = start_at_iso
    status["lastStep"] = None
    status["lastCompletedSteps"] = completed_steps.copy()
    status["lastTargetsProcessed"] = len(completed_steps)
    # Clear stale error/status from previous interrupted run
    status["lastRunError"] = None
    status["lastStatus"] = "running"
    status["lastRunOk"] = None
    status["lastMessage"] = f"{cst_now_str()} market_sentiment_chain running"
    _save_job_status(status)

    t0 = time.time()
    cst_time = cst_now_str()

    if not is_trading_day(now.date()):
        status["lastRunOk"] = True
        status["lastStatus"] = "skipped"
        status["lastRunError"] = f"{cst_time} 非交易日, 跳过串行 MSI 链路"
        status["lastDurationSeconds"] = round(time.time() - t0, 1)
        _save_job_status(status)
        _clear_checkpoint()
        _finish_history(
            final_status="skipped",
            duration_seconds=status.get("lastDurationSeconds"),
            error=status.get("lastRunError"),
        )
        return

    for step_code, runner, status_getter in remaining_steps:
        status["lastStep"] = step_code
        status["lastMessage"] = f"{cst_now_str()} running {step_code}"
        _save_job_status(status)
        try:
            runner(target_date=target_date)
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
            # Keep checkpoint — next restart will resume from completed steps
            _finish_history(
                final_status="failed",
                duration_seconds=status.get("lastDurationSeconds"),
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
            # Keep checkpoint — next restart will resume from completed steps
            _finish_history(
                final_status="failed",
                duration_seconds=status.get("lastDurationSeconds"),
                error=str(status.get("lastRunError") or "")[:500],
                message=f"stopped_at={step_code}",
            )
            return

        completed_steps.append(step_code)
        status["lastCompletedSteps"] = completed_steps.copy()
        status["lastTargetsProcessed"] = len(completed_steps)
        status["lastStepResults"] = step_results.copy()
        _save_job_status(status)
        _save_checkpoint(target_date, completed_steps)

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
    _clear_checkpoint()
    logger.info("market_sentiment_chain ok in %.1fs: steps=%d", status["lastDurationSeconds"], len(completed_steps))
    _finish_history(
        final_status="success",
        duration_seconds=status.get("lastDurationSeconds"),
        message=status.get("lastMessage"),
    )


def _job_run_chain(target_date=None) -> None:
    if not _run_lock.acquire(blocking=False):
        _record_already_running()
        return
    process_lock = _ChainProcessLock()
    if not process_lock.acquire():
        _run_lock.release()
        _record_already_running()
        return
    try:
        _job_run_chain_unlocked(target_date=target_date)
    finally:
        process_lock.release()
        _run_lock.release()


def _cleanup_interrupted_processing_runs() -> None:
    process_lock = _ChainProcessLock()
    if not process_lock.acquire():
        return
    try:
        message = f"{cst_now_str()} 上次执行进程未正常收尾, 已标记为中断"
        status = _load_job_status()
        count = mark_processing_interrupted(
            _JOB_ID,
            end_at=_beijing_now().isoformat(timespec="seconds"),
            message=message,
        )
        if count:
            status["lastRunOk"] = False
            status["lastStatus"] = "failed"
            status["lastRunError"] = message
            status["lastMessage"] = message
            status["totalFailures"] = int(status.get("totalFailures") or 0) + count
            _save_job_status(status)
            logger.warning("market_sentiment_chain marked %d interrupted processing history rows", count)
    finally:
        process_lock.release()


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

        _cleanup_interrupted_processing_runs()
        status = _load_job_status()

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


def run_market_sentiment_chain_now(target_date=None) -> dict[str, Any]:
    # Clear stale error immediately so frontend doesn't see old interrupted message
    status = _load_job_status()
    status["lastRunError"] = None
    status["lastStatus"] = "running"
    status["lastRunOk"] = None
    _save_job_status(status)

    def _run():
        with trigger_type("manual"):
            _job_run_chain(target_date=target_date)

    t = threading.Thread(target=_run, name="chain-manual-trigger", daemon=True)
    t.start()
    return {
        "ok": True,
        "items": [{"status": "started", "message": "chain 已在后台启动, 请刷新查看进度"}],
        "count": 1,
        "failed_count": 0,
    }
