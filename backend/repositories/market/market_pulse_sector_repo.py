"""市场脉搏 · 行业快照 PostgreSQL 仓储."""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from sqlalchemy import bindparam, text

from backend.config.database import session_scope
from backend.repositories.market.market_pg_cynexus_repo import coverage as _coverage, execute_upsert, to_date

logger = logging.getLogger(__name__)


def _to_date(v: date | str | None) -> date | None:
    return to_date(v)


def upsert_sector_spot(rows: list[dict[str, Any]], trade_date: date | str | None = None, source: str = "akshare.stock_fund_flow_industry") -> int:
    if not rows:
        return 0
    td = _to_date(trade_date) or date.today()
    n = 0
    with session_scope() as db:
        for r in rows:
            name = (r.get("name") or "").strip()
            if not name:
                continue
            execute_upsert(db, table="mkt_sector_pulse_daily", key_columns=["trade_date", "sector_name"], values={
                "trade_date": td,
                "sector_name": name,
                "sector_index": str(r.get("index") or "") or None,
                "change_pct": float(r.get("changePct") or 0),
                "inflow": float(r.get("inflow") or 0),
                "outflow": float(r.get("outflow") or 0),
                "main_net": float(r.get("mainNet") or 0),
                "stock_count": int(r.get("stockCount") or 0) if r.get("stockCount") is not None else None,
                "leading_stock": str(r.get("leadingStock") or "").strip() or None,
                "leading_change_pct": float(r.get("leadingChangePct")) if r.get("leadingChangePct") is not None else None,
                "leading_price": float(r.get("leadingPrice")) if r.get("leadingPrice") is not None else None,
                "source": source,
                "ingested_at": datetime.now(),
            })
            n += 1
    return n


_COLS = ("trade_date", "sector_name", "sector_index", "change_pct", "inflow", "outflow", "main_net", "stock_count", "leading_stock", "leading_change_pct", "leading_price", "source")
_COL_SELECT = ", ".join(_COLS)


def _row_to_payload(row: tuple | dict[str, Any]) -> dict[str, Any]:
    if isinstance(row, dict):
        r = row
        get = r.get
    else:
        keys = _COLS
        r = dict(zip(keys, row))
        get = r.get
    def _f(k: str) -> float | None:
        v = get(k)
        return float(v) if v is not None else None
    def _i(k: str) -> int | None:
        v = get(k)
        return int(v) if v is not None else None
    return {
        "tradeDate": get("trade_date").isoformat(),
        "name": str(get("sector_name")),
        "index": str(get("sector_index")) if get("sector_index") is not None else None,
        "changePct": _f("change_pct"),
        "inflow": _f("inflow"),
        "outflow": _f("outflow"),
        "mainNet": _f("main_net"),
        "stockCount": _i("stock_count"),
        "leadingStock": str(get("leading_stock")) if get("leading_stock") is not None else None,
        "leadingChangePct": _f("leading_change_pct"),
        "leadingPrice": _f("leading_price"),
        "source": str(get("source")) if get("source") is not None else None,
        "fromCache": True,
    }


def get_sector_daily(trade_date: date | str) -> list[dict[str, Any]]:
    td = _to_date(trade_date)
    if td is None:
        return []
    with session_scope() as db:
        rows = db.execute(text(f"SELECT {_COL_SELECT} FROM cynexus_appl_market.mkt_sector_pulse_daily WHERE trade_date = :td AND deleted_at IS NULL ORDER BY change_pct DESC"), {"td": td}).all()
    return [_row_to_payload(r) for r in rows]


def get_sector_daily_topn(trade_date: date | str, top_n: int = 10) -> dict[str, Any]:
    sectors = get_sector_daily(trade_date)
    if not sectors:
        return {"tradeDate": _to_date(trade_date).isoformat() if _to_date(trade_date) else None, "topN": top_n, "top": [], "bottom": [], "count": 0}
    return {"tradeDate": _to_date(trade_date).isoformat() if _to_date(trade_date) else sectors[0].get("tradeDate"), "topN": top_n, "top": sectors[:top_n], "bottom": list(reversed(sectors[-top_n:])) if len(sectors) >= top_n else list(reversed(sectors)), "count": len(sectors)}


def get_sector_history(days: int = 10, top_n: int | None = None) -> list[dict[str, Any]]:
    days = max(1, min(days, 120))
    with session_scope() as db:
        date_rows = db.execute(text("SELECT DISTINCT trade_date FROM cynexus_appl_market.mkt_sector_pulse_daily WHERE deleted_at IS NULL ORDER BY trade_date DESC LIMIT :days"), {"days": days}).all()
        out: list[dict[str, Any]] = []
        for (td,) in date_rows:
            limit_sql = " LIMIT :top_n" if top_n else ""
            params = {"td": td}
            if top_n:
                params["top_n"] = int(top_n)
            rows = db.execute(text(f"SELECT {_COL_SELECT} FROM cynexus_appl_market.mkt_sector_pulse_daily WHERE trade_date = :td AND deleted_at IS NULL ORDER BY change_pct DESC{limit_sql}"), params).all()
            out.append({"tradeDate": td.isoformat(), "items": [_row_to_payload(r) for r in rows]})
    return out


def get_sector_for_names(trade_date: date | str, names: list[str]) -> list[dict[str, Any]]:
    if not names:
        return []
    td = _to_date(trade_date)
    if td is None:
        return []
    with session_scope() as db:
        stmt = text(f"SELECT {_COL_SELECT} FROM cynexus_appl_market.mkt_sector_pulse_daily WHERE trade_date = :td AND sector_name IN :names AND deleted_at IS NULL ORDER BY change_pct DESC").bindparams(bindparam("names", expanding=True))
        rows = db.execute(stmt, {"td": td, "names": names}).all()
    return [_row_to_payload(r) for r in rows]


def coverage() -> dict[str, Any]:
    out = _coverage("mkt_sector_pulse_daily")
    with session_scope() as db:
        cnt = db.execute(text("SELECT COUNT(DISTINCT trade_date) FROM cynexus_appl_market.mkt_sector_pulse_daily WHERE deleted_at IS NULL")).scalar_one()
    out["tradeDayCount"] = int(cnt or 0)
    return out
