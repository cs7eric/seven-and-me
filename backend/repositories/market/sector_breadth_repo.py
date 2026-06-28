"""板块扩散 (Sector Breadth) 仓储 — PostgreSQL source/target."""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

from backend.config.database import session_scope
from backend.repositories.market.market_pg_cynexus_repo import execute_upsert, to_date

logger = logging.getLogger(__name__)


def _to_date(v: date | str | None) -> date | None:
    return to_date(v)


def upsert_sector_breadth(trade_date: date | str) -> int:
    td = _to_date(trade_date)
    if td is None:
        return 0
    t0 = time.time()
    with session_scope() as db:
        rows = db.execute(__import__("sqlalchemy").text("""
            SELECT COUNT(*) FILTER (WHERE change_pct > 0) AS advancing,
                   COUNT(*) FILTER (WHERE change_pct < 0) AS declining,
                   COUNT(*) FILTER (WHERE change_pct = 0) AS flat,
                   COUNT(*) AS total
              FROM cynexus_appl_market.mkt_ths_industry_fund_flow_daily
             WHERE trade_date = :td AND deleted_at IS NULL
        """), {"td": td}).first()
    if not rows or rows[3] is None:
        return 0
    advancing, declining, flat, total = int(rows[0] or 0), int(rows[1] or 0), int(rows[2] or 0), int(rows[3] or 0)
    if total <= 0:
        return 0
    advance_pct = round(advancing / total, 4)
    with session_scope() as db:
        execute_upsert(db, table="msi_sector_breadth_daily", key_columns=["trade_date"], values={
            "trade_date": td,
            "advancing": advancing,
            "declining": declining,
            "flat": flat,
            "total": total,
            "advance_pct": advance_pct,
            "source": "postgres.mkt_ths_industry_fund_flow_daily",
            "elapsed_ms": int((time.time() - t0) * 1000),
            "ingested_at": __import__("datetime").datetime.now(),
        })
    return 1


_COLS = ("trade_date", "advancing", "declining", "flat", "total", "advance_pct", "source", "elapsed_ms")
_COL_SELECT = ", ".join(_COLS)


def _row_to_payload(row: tuple) -> dict[str, Any]:
    advance_pct = float(row[5]) if row[5] is not None else 0.0
    return {"tradeDate": row[0].isoformat(), "advancing": int(row[1]) if row[1] is not None else 0, "declining": int(row[2]) if row[2] is not None else 0, "flat": int(row[3]) if row[3] is not None else 0, "total": int(row[4]) if row[4] is not None else 0, "advancePct": advance_pct, "score": round(advance_pct * 100, 2), "source": str(row[6]) if row[6] is not None else None, "elapsedMs": int(row[7]) if row[7] is not None else None, "fromCache": True}


def get_sector_breadth(trade_date: date | str) -> dict | None:
    td = _to_date(trade_date)
    if td is None:
        return None
    with session_scope() as db:
        row = db.execute(__import__("sqlalchemy").text(f"SELECT {_COL_SELECT} FROM cynexus_appl_market.msi_sector_breadth_daily WHERE trade_date = :td AND deleted_at IS NULL LIMIT 1"), {"td": td}).first()
    return _row_to_payload(row) if row else None


def get_sector_breadth_history(start: date | str, end: date | str | None = None, limit: int = 60) -> list[dict[str, Any]]:
    s = _to_date(start)
    e = _to_date(end) if end is not None else s
    if s is None or e is None:
        return []
    limit = max(1, min(limit, 365))
    with session_scope() as db:
        rows = db.execute(__import__("sqlalchemy").text(f"SELECT {_COL_SELECT} FROM cynexus_appl_market.msi_sector_breadth_daily WHERE trade_date BETWEEN :s AND :e AND deleted_at IS NULL ORDER BY trade_date DESC LIMIT :limit"), {"s": s, "e": e, "limit": limit}).all()
    return [_row_to_payload(r) for r in reversed(rows)]


def coverage() -> dict[str, Any]:
    with session_scope() as db:
        row = db.execute(__import__("sqlalchemy").text("SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM cynexus_appl_market.msi_sector_breadth_daily WHERE deleted_at IS NULL")).one()
    return {"firstDate": row[0].isoformat() if row[0] else None, "lastDate": row[1].isoformat() if row[1] else None, "rowCount": int(row[2]) if row[2] else 0}


def calc_sector_breadth_cached(trade_date: date | str, *, force: bool = False) -> dict | None:
    if not force:
        cached = get_sector_breadth(trade_date)
        if cached is not None:
            return {"ok": True, **cached}
    n = upsert_sector_breadth(trade_date)
    if n == 0:
        return None
    payload = get_sector_breadth(trade_date)
    return {"ok": True, **(payload or {})}
