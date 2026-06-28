"""最近一个交易日 resolver.

``is_trading_day`` (trading_calendar) 只看本地 HOLIDAYS 集合 + 周末判定, 偶尔
漏掉国务院临时调整 (e.g. 突发休市) 或本地 HOLIDAYS 没维护到的历史节假日.

更可靠的判定: 直接查 ClickHouse index_daily_raw 里 sh000001 是否有 K 线.
有 K 线 → 那一天 A 股有交易. 没有 → 那天没交易.

用法::

    from backend.services.stock.trading_day_resolver import (
        resolve_target_trading_day, resolve_target_trading_day_safe,
    )

    # 主入口: 给定 today → 返回最近一个交易日 (含 today)
    resolve_target_trading_day()                    # 今日 / 上一交易日
    resolve_target_trading_day(date(2026, 6, 20))  # 给定日期

    # 异常 / 不可用时返 None (不抛), 跟 ClickHouse 不可用 / 数据缺失 兼容
    resolve_target_trading_day_safe()
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from backend.services.stock.trading_calendar import is_trading_day, previous_trading_day

logger = logging.getLogger(__name__)

# 上证指数在 duckdb 里的 full code (跟 backend/repositories/market/index_repo.py
# 里 INDEX_TARGETS 一致). 改这里时同步改 index_repo.
SH_INDEX_FULL_CODE = "sh000001"

# 查 sh000001 时的兜底窗口天数 (查不到就继续往前). 5 个交易日足够 cover 周末 + 短假期.
_LOOKBACK_DAYS = 14


def _has_sh_kline(d: date, lookback_days: int = _LOOKBACK_DAYS) -> bool | None:
    """查 ClickHouse index_daily_raw 里 d (含) 之前最近 lookback_days 天内, sh000001
    是否有 K 线.

    返回:
      True  → d (含) 之前 ≤lookback_days 范围内, 至少 1 天有 sh000001 K 线
      False → 都没有 (可能 ClickHouse 还没建库, 也可能数据没拉)
      None  → 抛错 (ClickHouse 不可用 / 查询失败) — caller 决定 fallback
    """
    try:
        from backend.repositories.market.index_repo import latest_index_trade_date
        start = d - timedelta(days=lookback_days)
        last = latest_index_trade_date(SH_INDEX_FULL_CODE, d)
    except Exception as exc:  # noqa: BLE001
        logger.debug("sh k-line lookup failed for %s: %s", d, exc)
        return None
    return bool(last is not None and last >= start)


def resolve_target_trading_day(today: date | None = None) -> date:
    """返回 ``today`` (默认今天) 之前 (含) 最近的 A 股交易日.

    判定顺序 (3 层 fallback):
      1. 本地 trading_calendar.is_trading_day(today) → True 就直接返 today
         (覆盖了周末 + 本地 HOLIDAYS 维护到的节假日, 最快, 不查 duckdb)
      2. sh000001 K 线查询: 从 today 往前扫 14 天, 找到最近一个
         duckdb.index_daily_raw 里有 K 线的 trade_date.
         解决本地 HOLIDAYS 没维护到的节假日 / 临时休市.
      3. previous_trading_day(today) 本地 fallback (最坏情况: duckdb 不可用,
         用 trading_calendar 的 HOLIDAYS + 周末 + 调休 推算, 至少不会死锁).

    三层都没数据时 (极端情况) 仍然抛 previous_trading_day 的结果 (永远非 None).
    """
    if today is None:
        today = date.today()

    # 1) 本地 fast path
    if is_trading_day(today):
        return today

    # 2) 查 sh000001 K 线 (权威, 但要求 ClickHouse 可用 + sh000001 已落库)
    try:
        from backend.repositories.market.index_repo import latest_index_trade_date
        last = latest_index_trade_date(SH_INDEX_FULL_CODE, today)
    except Exception as exc:  # noqa: BLE001
        logger.debug("resolve_target_trading_day: ClickHouse query failed: %s", exc)
        return previous_trading_day(today)

    if last is not None:
        return last

    # 3) 本地 fallback
    return previous_trading_day(today)


def resolve_target_trading_day_safe(today: date | None = None) -> date | None:
    """跟 ``resolve_target_trading_day`` 一样, 但任何不可恢复错误时返 None (不抛).

    适合 status 报告 / 状态机: 让上层决定 fallback 策略.
    """
    try:
        return resolve_target_trading_day(today)
    except Exception as exc:  # noqa: BLE001
        logger.warning("resolve_target_trading_day_safe failed: %s", exc)
        return None


__all__ = [
    "resolve_target_trading_day",
    "resolve_target_trading_day_safe",
    "SH_INDEX_FULL_CODE",
]
