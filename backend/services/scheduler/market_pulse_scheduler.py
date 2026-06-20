"""Market Pulse 调度器:
  - 盘内 (9:30-11:30, 13:00-15:00) 每 10 分钟自动 snapshot 一次
  - 每个交易日 15:30 自动 snapshot 一次 (收盘后落盘)

启动方式: :mod:`backend.bootstrap` 调 :func:`start_market_pulse_scheduler`.
环境变量关闭: ``MINIMAX_MARKET_PULSE_SCHEDULER_ENABLED=0``.

状态文件: ``F:\\dev-repo\\mp4-to-word-new\\scheduler\\market_pulse_job.json``
Jobs 注册表: ``F:\\dev-repo\\mp4-to-word-new\\scheduler\\jobs.json``
"""
from __future__ import annotations

import logging
import os
import threading
import time
import traceback
from datetime import datetime, timedelta
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.services.scheduler.config_store import load_config, save_config, register_job
from backend.services.stock.market_pulse_service import snapshot_today_rotation
from backend.services.stock.f10.ths_industry_constituents_service import get_all_industry_constituents as get_all_constituents
from backend.services.stock.limit_emotion_service import snapshot_today_daily as snapshot_today_limit_emotion_daily
from backend.services.stock.trading_calendar import is_trade_time, is_trading_day

logger = logging.getLogger(__name__)

# 盘内刷新间隔 (秒). 10 分钟.
INSIDE_REFRESH_SECONDS = 10 * 60
SNAPSHOT_CRON = "30 15 * * mon-fri"  # 每天 15:30 (周末会被 is_trading_day 拦下)
CONSTITUENTS_CRON = "35 15 * * mon-fri"  # 15:35 拉 90 行业全量成分股 (Playwright 翻全页)


_scheduler: BackgroundScheduler | None = None
_scheduler_lock = threading.Lock()


def is_market_pulse_scheduler_enabled() -> bool:
    return os.environ.get("MINIMAX_MARKET_PULSE_SCHEDULER_ENABLED", "1") != "0"


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


# ---------------------------------------------------------------------------
# Job 状态
# ---------------------------------------------------------------------------
def _job_default_status() -> dict[str, Any]:
    return {
        "name": "market_pulse_snapshot",
        "lastRunAt": None,
        "lastRunOk": None,
        "lastRunError": None,
        "lastInsideRefreshAt": None,
        "lastCloseSnapshotAt": None,
        "totalInside": 0,
        "totalClose": 0,
        "schedulerStartedAt": None,
    }


def _load_job_status() -> dict[str, Any]:
    cfg = load_config("market_pulse_inside")
    if not cfg:
        return _job_default_status()
    return cfg


def _save_job_status(status: dict[str, Any]) -> None:
    save_config("market_pulse_inside", status)


# ---------------------------------------------------------------------------
# Job 注册 (DB)
# ---------------------------------------------------------------------------
def _register_job(job_id: str, name: str, next_run_time: str | None) -> None:
    register_job(
        code=job_id,
        name=name,
        description=(
            "交易时间内每 10 分钟刷新一次行业轮动快照；15:30 收盘后落盘当日完整 Top 10；"
            "15:35 (仅交易日) 拉 90 行业全量成分股 (Playwright 翻全页), "
            "落盘 reference/stock-universe/ths_industry/constituents/{code}.json"
        ),
        service_module="backend.services.scheduler.market_pulse_scheduler",
        service_class="MarketPulseScheduler",
        config_file="market_pulse_job.json",
        default_config=_job_default_status(),
    )


# ---------------------------------------------------------------------------
# Job 函数
# ---------------------------------------------------------------------------
def _job_inside_refresh() -> None:
    """盘内 10 分钟一次: 落盘当日 Top 10 + 顺手预热缓存."""
    now = _beijing_now()
    status = _load_job_status()
    if not is_trade_time(now):
        logger.debug("market_pulse inside-refresh skipped (not trade time): %s", now)
        return
    try:
        snap = snapshot_today_rotation(top_n=10, persist=True)
        status["lastInsideRefreshAt"] = now.isoformat(timespec="seconds")
        status["lastRunAt"] = status["lastInsideRefreshAt"]
        status["lastRunOk"] = True
        status["lastRunError"] = None
        status["totalInside"] = int(status.get("totalInside") or 0) + 1
        status["lastTopN"] = [
            {"name": x.get("name"), "changePct": x.get("changePct")} for x in (snap.get("items") or [])[:5]
        ]
        _save_job_status(status)
        logger.info("market_pulse inside-refresh ok, top5: %s", status["lastTopN"])
    except Exception as exc:
        status["lastRunOk"] = False
        status["lastRunError"] = str(exc)[:300]
        status["lastRunAt"] = now.isoformat(timespec="seconds")
        _save_job_status(status)
        logger.warning("market_pulse inside-refresh failed: %s\n%s", exc, traceback.format_exc())


def _job_close_snapshot() -> None:
    """15:30 收盘后强制落盘 (重置当日完整快照)."""
    now = _beijing_now()
    if not is_trading_day(now.date()):
        logger.info("market_pulse close-snapshot skipped: %s not trading day", now.date())
        return
    status = _load_job_status()
    try:
        snap = snapshot_today_rotation(top_n=10, persist=True)
        status["lastCloseSnapshotAt"] = now.isoformat(timespec="seconds")
        status["lastRunAt"] = status["lastCloseSnapshotAt"]
        status["lastRunOk"] = True
        status["lastRunError"] = None
        status["totalClose"] = int(status.get("totalClose") or 0) + 1
        status["lastTopN"] = [
            {"name": x.get("name"), "changePct": x.get("changePct")} for x in (snap.get("items") or [])[:5]
        ]
        _save_job_status(status)
        logger.info("market_pulse close-snapshot ok, top5: %s", status["lastTopN"])
    except Exception as exc:
        status["lastRunOk"] = False
        status["lastRunError"] = str(exc)[:300]
        _save_job_status(status)
        logger.warning("market_pulse close-snapshot failed: %s\n%s", exc, traceback.format_exc())

    # 涨跌停 daily 落盘: 供次日/非交易日连板读盘. 失败只 warn, 不影响 close snapshot 状态.
    try:
        daily_out = snapshot_today_limit_emotion_daily(force=False)
        if daily_out:
            status["lastLimitEmotionDailyAt"] = now.isoformat(timespec="seconds")
            _save_job_status(status)
            logger.info(
                "limitEmotion daily snapshot ok: %d stocks at %s",
                daily_out.get("stockCount"), daily_out.get("tradeDate"),
            )
    except Exception as exc:
        logger.warning("limitEmotion daily snapshot failed: %s\n%s", exc, traceback.format_exc())


def _job_constituents_refresh() -> None:
    """15:35 交易日拉 90 行业全量成分股 (Playwright 翻全页, 落盘每个行业 JSON).

    预计耗时 100-150s (4 worker 并发, 取决于每个行业页数)."""
    now = _beijing_now()
    if not is_trading_day(now.date()):
        logger.info("market_pulse constituents refresh skipped: %s not trading day", now.date())
        return
    status = _load_job_status()
    t0 = time.time()
    try:
        out = get_all_constituents(refresh=True)
        elapsed = round((time.time() - t0) * 1000)
        ok_count = sum(1 for v in out.values() if v)
        status["lastConstituentsAt"] = now.isoformat(timespec="seconds")
        status["lastConstituentsOk"] = True
        status["lastConstituentsError"] = None
        status["lastConstituentsElapseMs"] = elapsed
        status["lastConstituentsIndustriesOk"] = ok_count
        status["lastConstituentsIndustriesTotal"] = 90
        status["lastRunAt"] = status["lastConstituentsAt"]
        status["lastRunOk"] = True
        _save_job_status(status)
        logger.info("market_pulse constituents refresh ok: %d/90 in %dms", ok_count, elapsed)
    except Exception as exc:
        elapsed = round((time.time() - t0) * 1000)
        status["lastConstituentsAt"] = now.isoformat(timespec="seconds")
        status["lastConstituentsOk"] = False
        status["lastConstituentsError"] = str(exc)[:300]
        status["lastConstituentsElapseMs"] = elapsed
        status["lastRunAt"] = status["lastConstituentsAt"]
        status["lastRunOk"] = False
        status["lastRunError"] = str(exc)[:300]
        _save_job_status(status)
        logger.warning("market_pulse constituents refresh failed: %s\n%s", exc, traceback.format_exc())


# ---------------------------------------------------------------------------
# 启动 / 停止
# ---------------------------------------------------------------------------
def start_market_pulse_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    with _scheduler_lock:
        if _scheduler is not None:
            return
        # 检查 enabled 开关 (UI 禁用时不启动 APScheduler)
        status = _load_job_status()
        if not status.get("enabled", True):
            logger.info("[MarketPulseScheduler] disabled by config (market_pulse_job.json enabled=false), not started")
            return
        sched = BackgroundScheduler(timezone="Asia/Shanghai")

        # 1) 盘内 10 分钟一次: 用 interval trigger, 内部用 is_trade_time 判定
        sched.add_job(
            _job_inside_refresh,
            "interval",
            seconds=INSIDE_REFRESH_SECONDS,
            id="market_pulse_inside",
            max_instances=1,
            coalesce=True,
        )

        # 2) 收盘 15:30 落盘
        sched.add_job(
            _job_close_snapshot,
            CronTrigger.from_crontab(SNAPSHOT_CRON),
            id="market_pulse_close",
            max_instances=1,
            coalesce=True,
        )

        # 3) 15:35 拉 90 行业全量成分股 (Playwright 翻全页, 持久化到 constituents/{code}.json)
        sched.add_job(
            _job_constituents_refresh,
            CronTrigger.from_crontab(CONSTITUENTS_CRON),
            id="market_pulse_constituents",
            max_instances=1,
            coalesce=True,
        )

        sched.start()
        _scheduler = sched

        # 写状态 + 注册到 jobs.json
        status = _load_job_status()
        status["schedulerStartedAt"] = _beijing_now().isoformat(timespec="seconds")
        _save_job_status(status)
        _register_job("market_pulse_inside", "market_pulse_inside_refresh (10min, 交易时间内)", None)
        _register_job("market_pulse_close", "market_pulse_close_snapshot (15:30)", None)
        _register_job("market_pulse_constituents", "market_pulse_constituents_refresh (15:35, 90 行业全量)", None)
        logger.info("market_pulse_scheduler started: inside=10min, close=15:30, constituents=15:35")


def stop_market_pulse_scheduler() -> None:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            logger.info("market_pulse_scheduler stopped")


def get_market_pulse_scheduler_status() -> dict[str, Any]:
    """状态查询 (给 /api/.../market-pulse-scheduler/status 路由用)."""
    status = _load_job_status()
    status["isRunning"] = _scheduler is not None and _scheduler.running
    status["insideIntervalSeconds"] = INSIDE_REFRESH_SECONDS
    status["closeSnapshotCron"] = SNAPSHOT_CRON
    status["constituentsCron"] = CONSTITUENTS_CRON
    status["now"] = _beijing_now().isoformat(timespec="seconds")
    status["isTradeTime"] = is_trade_time()
    status["isTradingDay"] = is_trading_day()
    return status


def trigger_market_pulse_snapshot_now() -> dict[str, Any]:
    """手动触发一次盘内 refresh (绕开 is_trade_time 判定). 给 UI 立即触发按钮用."""
    if _scheduler is None or not _scheduler.running:
        return {"ok": False, "error": "market_pulse_scheduler not running"}
    started = datetime.now()
    try:
        _job_inside_refresh()
        return {"ok": True, "triggered": "market_pulse_inside", "elapsed_seconds": round((datetime.now() - started).total_seconds(), 3)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


def trigger_market_pulse_constituents_now() -> dict[str, Any]:
    """手动触发一次 90 行业全量成分股刷新 (绕开 is_trading_day 判定). 给 UI 立即触发按钮用."""
    if _scheduler is None or not _scheduler.running:
        return {"ok": False, "error": "market_pulse_scheduler not running"}
    started = datetime.now()
    try:
        _job_constituents_refresh()
        return {"ok": True, "triggered": "market_pulse_constituents", "elapsed_seconds": round((datetime.now() - started).total_seconds(), 3)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


def trigger_market_pulse_close_snapshot_now() -> dict[str, Any]:
    """手动触发一次 15:30 收盘落盘 (绕开 is_trading_day 判定). 给 UI 立即触发按钮用."""
    if _scheduler is None or not _scheduler.running:
        return {"ok": False, "error": "market_pulse_scheduler not running"}
    started = datetime.now()
    try:
        _job_close_snapshot()
        return {"ok": True, "triggered": "market_pulse_close", "elapsed_seconds": round((datetime.now() - started).total_seconds(), 3)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}
