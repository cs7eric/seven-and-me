"""赚钱效应 (Profit Effect) 仓储 — PostgreSQL cache over MSI MA count table."""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

from backend.config.database import session_scope
from backend.repositories.market.market_pg_cynexus_repo import execute_upsert, to_date
from backend.repositories.market.percentile_helper import enrich_history_scores, percentile_score
from backend.services.stock.trading_calendar import is_trading_day

logger = logging.getLogger(__name__)


def _to_date(v: date | str | None) -> date | None:
    return to_date(v)


def _pct(num: float, den: float) -> float:
    return round(num / den * 100, 2) if den > 0 else 0.0


def calc_profit_effect(trade_date: date | str) -> dict[str, Any] | None:
    td = _to_date(trade_date)
    if td is None:
        return None
    t0 = time.time()
    with session_scope() as db:
        row = db.execute(__import__("sqlalchemy").text("SELECT up_5d_pct, new_low_60d_pct FROM cynexus_appl_market.msi_ma_count_daily WHERE trade_date = :td AND deleted_at IS NULL LIMIT 1"), {"td": td}).first()
    if not row:
        return None
    up5d_pct = float(row[0]) if row[0] is not None else 0
    new_low_pct = float(row[1]) if row[1] is not None else 0
    score = round(0.60 * up5d_pct + 0.40 * (100 - new_low_pct), 2)
    return {"tradeDate": td.isoformat(), "up5dPct": up5d_pct, "newLow60dPct": new_low_pct, "score": score, "elapsedMs": int((time.time() - t0) * 1000), "source": "postgres.msi_ma_count_daily"}


def save_profit_effect(payload: dict) -> None:
    td = _to_date(payload.get("tradeDate"))
    if td is None:
        raise ValueError("payload.tradeDate required")
    if not is_trading_day(td):
        logger.debug("save_profit_effect skipped non-trading day: %s", td)
        return
    with session_scope() as db:
        execute_upsert(db, table="msi_profit_effect_daily", key_columns=["trade_date"], values={
            "trade_date": td,
            "up_5d_pct": float(payload.get("up5dPct") or 0),
            "new_low_60d_pct": float(payload.get("newLow60dPct") or 0),
            "score": float(payload.get("score") or 0),
            "elapsed_ms": int(payload.get("elapsedMs") or 0),
            "source": str(payload.get("source") or "postgres.msi_ma_count_daily"),
            "ingested_at": __import__("datetime").datetime.now(),
        })


_PE_COLS = ("trade_date", "up_5d_pct", "new_low_60d_pct", "score", "elapsed_ms", "source")
_PE_SELECT = ", ".join(_PE_COLS)


def _row_to_payload(row: tuple) -> dict:
    return {"tradeDate": row[0].isoformat(), "up5dPct": float(row[1]) if row[1] is not None else None, "newLow60dPct": float(row[2]) if row[2] is not None else None, "score": float(row[3]) if row[3] is not None else None, "elapsedMs": int(row[4]) if row[4] is not None else None, "source": str(row[5]) if row[5] else None, "fromCache": True}


def get_profit_effect(trade_date: date | str) -> dict | None:
    td = _to_date(trade_date)
    if td is None:
        return None
    with session_scope() as db:
        row = db.execute(__import__("sqlalchemy").text(f"SELECT {_PE_SELECT} FROM cynexus_appl_market.msi_profit_effect_daily WHERE trade_date = :td AND deleted_at IS NULL LIMIT 1"), {"td": td}).first()
    return _row_to_payload(row) if row else None


def get_profit_effect_history(start: date | str, end: date | str | None = None) -> list[dict]:
    s = _to_date(start)
    e = _to_date(end) if end is not None else s
    if s is None or e is None:
        return []
    with session_scope() as db:
        rows = db.execute(__import__("sqlalchemy").text(f"SELECT {_PE_SELECT} FROM cynexus_appl_market.msi_profit_effect_daily WHERE trade_date BETWEEN :s AND :e AND deleted_at IS NULL ORDER BY trade_date ASC"), {"s": s, "e": e}).all()
    items = [_row_to_payload(r) for r in rows]
    enrich_history_scores(items, "profit_effect_daily", "score", e)
    return items


def _add_score(payload: dict, trade_date: date | str) -> None:
    raw = payload.get("score")
    if raw is not None:
        payload["score"] = percentile_score("profit_effect_daily", "score", trade_date, raw)
        payload["rawValue"] = raw


def calc_profit_effect_cached(trade_date: date | str, *, force: bool = False) -> dict | None:
    if not force:
        cached = get_profit_effect(trade_date)
        if cached is not None:
            _add_score(cached, trade_date)
            return cached
    payload = calc_profit_effect(trade_date)
    if payload is None:
        return None
    try:
        save_profit_effect(payload)
    except Exception:
        logger.debug("save_profit_effect failed (non-fatal): %s", payload.get("tradeDate"))
    _add_score(payload, trade_date)
    return payload
