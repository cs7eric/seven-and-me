r"""Trading-day utilities shared by market-data features.

维护前请先看:
`F:\dev-repo\mp4-to-word-new\design\backend\industry-concept-fund-flow-postgres-migration.md`

这里封装两类规则:
1. 用腾讯指数日线确认某个历史日期是否真的是交易日
2. 给“只能抓当日网页快照”的功能决定当前应该读哪一天、能不能写哪一天
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache

from backend.adapters.market.tencent import fetch_stock_klines_from_tencent
from backend.services.stock.trading_calendar import is_trading_day, previous_trading_day

TENCENT_INDEX_SYMBOLS: tuple[str, str] = ("000001", "399001")
_PRE_MARKET_MINUTES = 9 * 60 + 30


def beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def beijing_today() -> date:
    return beijing_now().date()


def _minutes_of_day(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def _to_date(value: date | str | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def can_validate_trade_date_with_tencent(target_date: date | str, *, now: datetime | None = None) -> bool:
    td = _to_date(target_date)
    if td is None:
        return False
    current = now or beijing_now()
    today = current.date()
    if td < today:
        return True
    if td > today:
        return False
    return _minutes_of_day(current) >= _PRE_MARKET_MINUTES


@lru_cache(maxsize=512)
def _has_tencent_index_bar(symbol: str, trade_date_iso: str) -> bool:
    rows = fetch_stock_klines_from_tencent("index", symbol, "1d", "")
    return any(str(item.get("trade_date")) == trade_date_iso for item in rows)


def is_trade_date_confirmed_by_tencent(
    target_date: date | str,
    *,
    now: datetime | None = None,
) -> bool | None:
    td = _to_date(target_date)
    if td is None:
        return False
    if not can_validate_trade_date_with_tencent(td, now=now):
        return None
    trade_date_iso = td.isoformat()
    return all(_has_tencent_index_bar(symbol, trade_date_iso) for symbol in TENCENT_INDEX_SYMBOLS)


def can_request_live_fund_flow_snapshot(
    target_date: date | str | None = None,
    *,
    now: datetime | None = None,
) -> bool:
    current = now or beijing_now()
    today = current.date()
    td = _to_date(target_date) or today
    if td != today:
        return False
    if not is_trading_day(today):
        return False
    return _minutes_of_day(current) >= _PRE_MARKET_MINUTES


def resolve_previous_confirmed_trade_date(
    target_date: date | str | None = None,
    *,
    max_lookback_days: int = 30,
    now: datetime | None = None,
) -> date:
    current = now or beijing_now()
    candidate = _to_date(target_date) or current.date()
    probe = previous_trading_day(candidate) if candidate >= current.date() else candidate
    for _ in range(max_lookback_days):
        confirmed = is_trade_date_confirmed_by_tencent(probe, now=current)
        if confirmed is True:
            return probe
        probe = previous_trading_day(probe)
    return previous_trading_day(candidate)


def resolve_fund_flow_read_trade_date(
    target_date: date | str | None = None,
    *,
    now: datetime | None = None,
) -> date:
    current = now or beijing_now()
    td = _to_date(target_date) or current.date()
    if can_request_live_fund_flow_snapshot(td, now=current):
        return td
    confirmed = is_trade_date_confirmed_by_tencent(td, now=current)
    if confirmed is True:
        return td
    return resolve_previous_confirmed_trade_date(td, now=current)


__all__ = [
    "beijing_now",
    "beijing_today",
    "can_request_live_fund_flow_snapshot",
    "can_validate_trade_date_with_tencent",
    "is_trade_date_confirmed_by_tencent",
    "resolve_fund_flow_read_trade_date",
    "resolve_previous_confirmed_trade_date",
]
