"""大盘数据 (成交额 / 主力净流入) 调度器.

三组 jobs:
  1. **盘内 5 分钟一次** (``market_overview_inside``):
     interval 5min, 内部用 ``is_trade_time`` 判定, 非交易时间自动 skip.
  2. **收盘 15:35 落盘** (``market_overview_close``):
     cron ``35 15 * * mon-fri`` + is_trading_day, 兜底补当日完整 snapshot.
  3. **周一开盘前 09:00 周末补落** (``market_overview_warm``):
     cron ``0 9 * * mon-fri``, 启动时 warmup 拉一次, 防止冷启动时 latest.json 为空.

启动: :mod:`backend.bootstrap` 调 :func:`start_market_overview_scheduler`.
关闭: ``MINIMAX_MARKET_OVERVIEW_SCHEDULER_ENABLED=0``.

状态文件: ``F:\\dev-repo\\mp4-to-word-new\\scheduler\\market_overview_job.json``
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
from backend.services.stock.market_overview_akshare_service import (
    capture_snapshot,
    get_latest_snapshot,
    get_archived_snapshot,
)
from backend.services.stock.market_overview_eltdx_service import (
    capture_overview,
    get_latest_overview,
)
from backend.services.stock.trading_calendar import is_trade_time, is_trading_day

logger = logging.getLogger(__name__)

# 盘内刷新间隔 (秒). 5 分钟.
INSIDE_REFRESH_SECONDS = 5 * 60
CLOSE_SNAPSHOT_CRON = "35 15 * * mon-fri"  # 15:35 收盘后兜底落盘
WARMUP_CRON = "0 9 * * mon-fri"           # 09:00 开盘前 warm 一次

_scheduler: BackgroundScheduler | None = None
_scheduler_lock = threading.Lock()


def is_market_overview_scheduler_enabled() -> bool:
    return os.environ.get("MINIMAX_MARKET_OVERVIEW_SCHEDULER_ENABLED", "1") != "0"


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


# ---------------------------------------------------------------------------
# Job 状态
# ---------------------------------------------------------------------------
def _job_default_status() -> dict[str, Any]:
    return {
        "name": "market_overview_snapshot",
        "lastRunAt": None,
        "lastRunOk": None,
        "lastRunError": None,
        "lastInsideRefreshAt": None,
        "lastCloseSnapshotAt": None,
        "lastWarmupAt": None,
        "totalInside": 0,
        "totalClose": 0,
        "totalWarmup": 0,
        "schedulerStartedAt": None,
    }


def _load_job_status() -> dict[str, Any]:
    cfg = load_config("market_overview_inside")
    if not cfg:
        return _job_default_status()
    return cfg


def _save_job_status(status: dict[str, Any]) -> None:
    save_config("market_overview_inside", status)


# ---------------------------------------------------------------------------
# Job 注册 (DB)
# ---------------------------------------------------------------------------
_JOB_CODES = [
    "market_overview_inside",
    "market_overview_close",
    "market_overview_warmup",
    "eltdx_overview_inside",
    "eltdx_overview_close",
    "eltdx_overview_warmup",
]


def _register_job(job_id: str, name: str, next_run_time: str | None) -> None:
    register_job(
        code=job_id,
        name=name,
        description=(
            "盘内 5 分钟一次 (fund-flow akshare + eltdx overview) + 15:35 收盘落盘 + 09:00 开盘前 warmup, "
            "落盘 reference/market-overview/latest.json + reference/stock-universe/market_pulse/rotation/YYYY-MM-DD.json, "
            "供前端 Market Overview / Sector Rotation / 涨跌家数 视图使用"
        ),
        service_module="backend.services.scheduler.market_overview_scheduler",
        service_class="MarketOverviewScheduler",
        config_file="market_overview_job.json",
        default_config=_job_default_status(),
    )


# ---------------------------------------------------------------------------
# Job 函数
# ---------------------------------------------------------------------------
def _job_inside_refresh() -> None:
    """盘内 5 分钟一次, 非交易时间自动 skip."""
    now = _beijing_now()
    status = _load_job_status()
    if not is_trade_time(now):
        logger.debug("market_overview inside-refresh skipped (not trade time): %s", now)
        return
    if not is_trading_day(now.date()):
        logger.debug("market_overview inside-refresh skipped (not trading day): %s", now)
        return
    t0 = time.time()
    try:
        snap = capture_snapshot(force=False, source="akshare")
        elapsed_ms = int((time.time() - t0) * 1000)
        status["lastInsideRefreshAt"] = now.isoformat(timespec="seconds")
        status["lastRunAt"] = status["lastInsideRefreshAt"]
        if snap:
            status["lastRunOk"] = True
            status["lastRunError"] = None
            status["totalInside"] = int(status.get("totalInside") or 0) + 1
            status["lastInside"] = {
                "tradingDate": snap.get("tradingDate"),
                "totalAmount": snap.get("totalAmount"),
                "mainNetInflow": snap.get("mainNetInflow"),
                "elapsedMs": elapsed_ms,
            }
        else:
            status["lastRunOk"] = False
            status["lastRunError"] = "snapshot returned None (akshare unavailable)"
        _save_job_status(status)
        logger.info("market_overview inside-refresh ok in %dms: %s", elapsed_ms, status.get("lastInside"))
    except Exception as exc:
        elapsed_ms = int((time.time() - t0) * 1000)
        status["lastRunOk"] = False
        status["lastRunError"] = str(exc)[:300]
        status["lastRunAt"] = now.isoformat(timespec="seconds")
        _save_job_status(status)
        logger.warning("market_overview inside-refresh failed in %dms: %s\n%s", elapsed_ms, exc, traceback.format_exc())


def _job_close_snapshot() -> None:
    """15:35 收盘后强制落盘, 跳过周末/节假日."""
    now = _beijing_now()
    if not is_trading_day(now.date()):
        logger.info("market_overview close-snapshot skipped: %s not trading day", now.date())
        return
    status = _load_job_status()
    t0 = time.time()
    try:
        snap = capture_snapshot(force=True, source="akshare")
        elapsed_ms = int((time.time() - t0) * 1000)
        status["lastCloseSnapshotAt"] = now.isoformat(timespec="seconds")
        status["lastRunAt"] = status["lastCloseSnapshotAt"]
        if snap:
            status["lastRunOk"] = True
            status["lastRunError"] = None
            status["totalClose"] = int(status.get("totalClose") or 0) + 1
            status["lastClose"] = {
                "tradingDate": snap.get("tradingDate"),
                "totalAmount": snap.get("totalAmount"),
                "mainNetInflow": snap.get("mainNetInflow"),
                "elapsedMs": elapsed_ms,
            }
        else:
            status["lastRunOk"] = False
            status["lastRunError"] = "force snapshot returned None"
        _save_job_status(status)
        logger.info("market_overview close-snapshot ok in %dms: %s", elapsed_ms, status.get("lastClose"))
    except Exception as exc:
        elapsed_ms = int((time.time() - t0) * 1000)
        status["lastRunOk"] = False
        status["lastRunError"] = str(exc)[:300]
        status["lastRunAt"] = now.isoformat(timespec="seconds")
        _save_job_status(status)
        logger.warning("market_overview close-snapshot failed in %dms: %s\n%s", elapsed_ms, exc, traceback.format_exc())


def _job_warmup() -> None:
    """09:00 开盘前 warmup: 拉一次, 防止冷启动时 latest.json 缺失 (周末/节假日 后)."""
    now = _beijing_now()
    if not is_trading_day(now.date()):
        logger.info("market_overview warmup skipped: %s not trading day", now.date())
        return
    status = _load_job_status()
    t0 = time.time()
    try:
        # warmup 用 force=True 绕过 trade_time 判定 (09:00 不在 09:30-11:30 / 13:00-15:00)
        snap = capture_snapshot(force=True, source="akshare")
        elapsed_ms = int((time.time() - t0) * 1000)
        status["lastWarmupAt"] = now.isoformat(timespec="seconds")
        status["lastRunAt"] = status["lastWarmupAt"]
        if snap:
            status["lastRunOk"] = True
            status["lastRunError"] = None
            status["totalWarmup"] = int(status.get("totalWarmup") or 0) + 1
        else:
            status["lastRunOk"] = False
            status["lastRunError"] = "warmup snapshot returned None"
        _save_job_status(status)
        logger.info("market_overview warmup ok in %dms", elapsed_ms)
    except Exception as exc:
        elapsed_ms = int((time.time() - t0) * 1000)
        status["lastRunOk"] = False
        status["lastRunError"] = str(exc)[:300]
        status["lastRunAt"] = now.isoformat(timespec="seconds")
        _save_job_status(status)
        logger.warning("market_overview warmup failed in %dms: %s\n%s", elapsed_ms, exc, traceback.format_exc())


# ---------------------------------------------------------------------------
# Eltdx 市场概况 job 函数 (独立于 fund-flow, 不互相影响)
# ---------------------------------------------------------------------------
def _job_eltdx_inside() -> None:
    """eltdx 市场概况: 盘内 5 分钟一次."""
    now = _beijing_now()
    if not is_trade_time(now):
        return
    if not is_trading_day(now.date()):
        return
    try:
        snap = capture_overview(force=False)
        if snap:
            logger.info(
                "eltdx overview inside ok: totalAmount=%.2f亿, rising=%d, elapsed=%.1fs",
                snap.get("totalAmount") or 0,
                snap.get("risingCount") or 0,
                time.time() - time.time(),
            )
    except Exception as exc:
        logger.warning("eltdx overview inside failed: %s", exc)


def _job_eltdx_close() -> None:
    """eltdx 市场概况: 15:35 收盘后强制拉一次."""
    now = _beijing_now()
    if not is_trading_day(now.date()):
        return
    try:
        snap = capture_overview(force=True)
        if snap:
            logger.info(
                "eltdx overview close ok: totalAmount=%.2f亿",
                snap.get("totalAmount") or 0,
            )
    except Exception as exc:
        logger.warning("eltdx overview close failed: %s", exc)


def _job_eltdx_warmup() -> None:
    """eltdx 市场概况: 09:00 开盘前 warmup.

    09:00 这一刻 eltdx 抓到的数据是"开盘集合竞价"状态: 涨跌停 + 涨跌家数全是错的
    (例: fallingCount=5527, limitDownCount=5527, 因为实时价格等于昨日收盘的 -10%).
    warmup 只为防止 latest.json 完全缺失, 不应该写入脏数据.
    因此: 9:30 之前跳过; 9:30 之后按盘内 inside 处理.
    """
    now = _beijing_now()
    if not is_trading_day(now.date()):
        return
    # 9:30 之前 skip — 防止 eltdx 把集合竞价的脏数据写进 latest.json
    hm = now.hour * 60 + now.minute
    if hm < 9 * 60 + 30:
        logger.info("eltdx overview warmup skipped: %s before 09:30", now.time())
        return
    try:
        snap = capture_overview(force=True)
        if snap:
            logger.info(
                "eltdx overview warmup ok: totalAmount=%.2f亿",
                snap.get("totalAmount") or 0,
            )
    except Exception as exc:
        logger.warning("eltdx overview warmup failed: %s", exc)


# ---------------------------------------------------------------------------
# 启动 / 停止 / 状态
# ---------------------------------------------------------------------------
def start_market_overview_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    with _scheduler_lock:
        if _scheduler is not None:
            return
        # 检查 enabled 开关 (UI 禁用时不启动 APScheduler)
        status = _load_job_status()
        if not status.get("enabled", True):
            logger.info("[MarketOverviewScheduler] disabled by config (market_overview_job.json enabled=false), not started")
            return
        sched = BackgroundScheduler(timezone="Asia/Shanghai")

        # 1) 盘内 5 分钟一次 (内部 is_trade_time 判定)
        sched.add_job(
            _job_inside_refresh,
            "interval",
            seconds=INSIDE_REFRESH_SECONDS,
            id="market_overview_inside",
            max_instances=1,
            coalesce=True,
        )

        # 2) 15:35 收盘后兜底落盘
        sched.add_job(
            _job_close_snapshot,
            CronTrigger.from_crontab(CLOSE_SNAPSHOT_CRON),
            id="market_overview_close",
            max_instances=1,
            coalesce=True,
        )

        # 3) 09:00 开盘前 warmup (force 拉一次)
        sched.add_job(
            _job_warmup,
            CronTrigger.from_crontab(WARMUP_CRON),
            id="market_overview_warmup",
            max_instances=1,
            coalesce=True,
        )

        # 4) eltdx 市场概况: 盘内 5 分钟一次
        sched.add_job(
            _job_eltdx_inside,
            "interval",
            seconds=INSIDE_REFRESH_SECONDS,
            id="eltdx_overview_inside",
            max_instances=1,
            coalesce=True,
        )

        # 5) eltdx 市场概况: 15:35 收盘后强制拉一次
        sched.add_job(
            _job_eltdx_close,
            CronTrigger.from_crontab(CLOSE_SNAPSHOT_CRON),
            id="eltdx_overview_close",
            max_instances=1,
            coalesce=True,
        )

        # 6) eltdx 市场概况: 09:00 开盘前 warmup
        sched.add_job(
            _job_eltdx_warmup,
            CronTrigger.from_crontab(WARMUP_CRON),
            id="eltdx_overview_warmup",
            max_instances=1,
            coalesce=True,
        )

        sched.start()
        _scheduler = sched

        # 写状态 + 注册到 jobs.json
        status = _load_job_status()
        status["schedulerStartedAt"] = _beijing_now().isoformat(timespec="seconds")
        _save_job_status(status)
        _register_job("market_overview_inside", "market_overview_inside_refresh (5min, 交易时间内)", None)
        _register_job("market_overview_close", "market_overview_close_snapshot (15:35)", None)
        _register_job("market_overview_warmup", "market_overview_warmup (09:00, 开盘前)", None)
        _register_job("eltdx_overview_inside", "eltdx_overview_inside (5min, 交易时间内)", None)
        _register_job("eltdx_overview_close", "eltdx_overview_close (15:35)", None)
        _register_job("eltdx_overview_warmup", "eltdx_overview_warmup (09:00, 开盘前)", None)
        logger.info(
            "market_overview_scheduler started: inside=5min, warm=09:00, close=15:35 "
            "(fund-flow + eltdx overview)"
        )

    # 更新状态文件: running=true (供前端 JobCard 显示)
    status = _load_job_status()
    status["running"] = True
    status["schedulerStartedAt"] = _beijing_now().isoformat(timespec="seconds")
    _save_job_status(status)


def stop_market_overview_scheduler() -> None:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            logger.info("market_overview_scheduler stopped")

    # 更新状态文件: running=false
    status = _load_job_status()
    status["running"] = False
    status["stoppedAt"] = _beijing_now().isoformat(timespec="seconds")
    status["lastRunAt"] = status.get("stoppedAt")
    _save_job_status(status)


def get_market_overview_scheduler_status() -> dict[str, Any]:
    """返回 status, 但补上 running 字段 (从 _scheduler 实例推算).

    注意: status 文件里也保存了 running, 但可能跟 _scheduler 实例不同步
    (比如 start 后 status 写了 running=true, 之后从未停过).
    所以这里以 _scheduler 实例为准, status 文件仅作持久化展示.
    """
    status = _load_job_status()
    status["running"] = _scheduler is not None
    return status


def run_market_overview_snapshot_now(force: bool = False) -> dict[str, Any] | None:
    """手动触发一次 (前端 / API 测试用)."""
    return capture_snapshot(force=force, source="akshare")
