"""大盘概况 (成交额 / 主力净流入 / 涨跌家数) PostgreSQL 仓储."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import text

from backend.config.database import session_scope
from backend.repositories.market.market_pg_cynexus_repo import coverage as _coverage, execute_upsert, to_date


def _to_date(v: date | str | None) -> date | None:
    return to_date(v)


_UPSERT_FIELDS = [
    ("total_amount", "totalAmount"),
    ("total_volume", "totalVolume"),
    ("rising_count", "risingCount"),
    ("falling_count", "fallingCount"),
    ("flat_count", "flatCount"),
    ("limit_up_count", "limitUpCount"),
    ("limit_down_count", "limitDownCount"),
    ("stock_count", "stockCount"),
    ("main_net_inflow", "mainNetInflow"),
    ("super_large_net_inflow", "superLargeNetInflow"),
    ("large_net_inflow", "largeNetInflow"),
    ("medium_net_inflow", "mediumNetInflow"),
    ("small_net_inflow", "smallNetInflow"),
    ("main_net_inflow_ratio", "mainNetInflowRatio"),
    ("super_large_net_ratio", "superLargeNetInflowRatio"),
    ("large_net_ratio", "largeNetInflowRatio"),
    ("medium_net_ratio", "mediumNetInflowRatio"),
    ("small_net_ratio", "smallNetInflowRatio"),
]


def _values_from_payload(payload: dict[str, Any], *, default_source: str) -> dict[str, Any]:
    td = _to_date(payload.get("tradingDate") or payload.get("trade_date"))
    if td is None:
        raise ValueError("payload.tradingDate required")
    values: dict[str, Any] = {
        "trade_date": td,
        "source": str(payload.get("source") or default_source),
        "ingested_at": datetime.now(),
    }
    for col, key in _UPSERT_FIELDS:
        if payload.get(key) is not None:
            values[col] = payload.get(key)
    return values


def upsert_overview_akshare(payload: dict[str, Any]) -> None:
    values = _values_from_payload(payload, default_source="akshare")
    with session_scope() as db:
        execute_upsert(
            db,
            table="mkt_overview_daily",
            key_columns=["trade_date"],
            values=values,
        )


def upsert_overview_eltdx(payload: dict[str, Any]) -> None:
    td = _to_date(payload.get("tradingDate") or payload.get("trade_date"))
    if td is None:
        return
    mapped = {
        "tradingDate": td,
        "source": "eltdx",
        "totalAmount": payload.get("totalAmount"),
        "risingCount": payload.get("risingCount"),
        "fallingCount": payload.get("fallingCount"),
        "flatCount": payload.get("flatCount"),
        "limitUpCount": payload.get("limitUpCount"),
        "limitDownCount": payload.get("limitDownCount"),
        "stockCount": payload.get("stockCount"),
    }
    if not any(mapped.get(k) is not None for k in mapped if k not in {"tradingDate", "source"}):
        return
    values = _values_from_payload(mapped, default_source="eltdx")
    with session_scope() as db:
        execute_upsert(db, table="mkt_overview_daily", key_columns=["trade_date"], values=values)


_COLS = (
    "trade_date", "total_amount", "total_volume",
    "rising_count", "falling_count", "flat_count",
    "limit_up_count", "limit_down_count", "stock_count",
    "main_net_inflow", "super_large_net_inflow", "large_net_inflow",
    "medium_net_inflow", "small_net_inflow",
    "main_net_inflow_ratio", "super_large_net_ratio", "large_net_ratio",
    "medium_net_ratio", "small_net_ratio",
    "source",
)
_COL_SELECT = ", ".join(_COLS)


def _row_to_payload(row: Any) -> dict[str, Any]:
    r = row if isinstance(row, dict) else dict(row)
    def _f(k: str) -> float | None:
        v = r.get(k)
        return float(v) if v is not None else None
    def _i(k: str) -> int | None:
        v = r.get(k)
        return int(v) if v is not None else None
    return {
        "tradeDate": r["trade_date"].isoformat(),
        "totalAmount": _f("total_amount"),
        "totalVolume": _f("total_volume"),
        "risingCount": _i("rising_count"),
        "fallingCount": _i("falling_count"),
        "flatCount": _i("flat_count"),
        "limitUpCount": _i("limit_up_count"),
        "limitDownCount": _i("limit_down_count"),
        "stockCount": _i("stock_count"),
        "mainNetInflow": _f("main_net_inflow"),
        "superLargeNetInflow": _f("super_large_net_inflow"),
        "largeNetInflow": _f("large_net_inflow"),
        "mediumNetInflow": _f("medium_net_inflow"),
        "smallNetInflow": _f("small_net_inflow"),
        "mainNetInflowRatio": _f("main_net_inflow_ratio"),
        "superLargeNetInflowRatio": _f("super_large_net_ratio"),
        "largeNetInflowRatio": _f("large_net_ratio"),
        "mediumNetInflowRatio": _f("medium_net_ratio"),
        "smallNetInflowRatio": _f("small_net_ratio"),
        "source": str(r["source"]) if r.get("source") is not None else None,
        "fromCache": True,
    }


def get_overview(trade_date: date | str) -> dict | None:
    td = _to_date(trade_date)
    if td is None:
        return None
    with session_scope() as db:
        row = db.execute(
            text(f"SELECT {_COL_SELECT} FROM cynexus_appl_market.mkt_overview_daily WHERE trade_date = :td AND deleted_at IS NULL LIMIT 1"),
            {"td": td},
        ).mappings().first()
    return _row_to_payload(dict(row)) if row else None


def get_overview_history(start: date | str, end: date | str | None = None, limit: int = 60) -> list[dict[str, Any]]:
    s = _to_date(start)
    e = _to_date(end) if end is not None else s
    if s is None or e is None:
        return []
    limit = max(1, min(limit, 500))
    with session_scope() as db:
        rows = db.execute(
            text(f"""
                SELECT {_COL_SELECT}
                  FROM cynexus_appl_market.mkt_overview_daily
                 WHERE trade_date BETWEEN :s AND :e AND deleted_at IS NULL
                 ORDER BY trade_date DESC
                 LIMIT :limit
            """),
            {"s": s, "e": e, "limit": limit},
        ).mappings().all()
    return [_row_to_payload(dict(r)) for r in reversed(rows)]


def coverage() -> dict[str, Any]:
    return _coverage("mkt_overview_daily")
