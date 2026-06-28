"""市场情绪指数 (Market Sentiment Index) 仓储 — PostgreSQL component tables."""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

from backend.config.database import session_scope
from backend.repositories.market.market_pg_cynexus_repo import execute_upsert, to_date
from backend.repositories.market.percentile_helper import percentile_score
from backend.services.stock.trading_calendar import is_trading_day

logger = logging.getLogger(__name__)
WEIGHTS = {"vol": 0.15, "turnover": 0.15, "price_strength": 0.10, "risk_appetite": 0.10, "breadth": 0.15, "limit_emotion": 0.15, "profit_effect": 0.10, "sector_breadth": 0.05, "style_risk": 0.05}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9
_MISSING_SCORE = 50.0


def _to_date(v: date | str | None) -> date | None:
    return to_date(v)


def _has_turnover_activity_row(td: date) -> bool:
    with session_scope() as db:
        row = db.execute(__import__("sqlalchemy").text("SELECT 1 FROM cynexus_appl_market.msi_turnover_activity_daily WHERE trade_date = :td AND deleted_at IS NULL LIMIT 1"), {"td": td}).first()
    return bool(row)


def _is_valid_msi_trade_date(td: date) -> bool:
    today = date.today()
    if td < today:
        return _has_turnover_activity_row(td)
    return is_trading_day(td)


def _fetch_col(table: str, column: str, td: date) -> float | None:
    with session_scope() as db:
        row = db.execute(__import__("sqlalchemy").text(f"SELECT {column} FROM cynexus_appl_market.{table} WHERE trade_date = :td AND deleted_at IS NULL LIMIT 1"), {"td": td}).first()
    return float(row[0]) if row and row[0] is not None else None


def _fetch_vol_score(td: date) -> float | None: return _fetch_col("msi_volatility_daily", "sentiment_score", td)

def _fetch_turnover_score(td: date) -> float | None:
    with session_scope() as db:
        row = db.execute(__import__("sqlalchemy").text("SELECT score, ratio FROM cynexus_appl_market.msi_turnover_activity_daily WHERE trade_date = :td AND deleted_at IS NULL LIMIT 1"), {"td": td}).first()
    if not row:
        return None
    if row[0] is not None:
        return round(float(row[0]), 2)
    if row[1] is None:
        return None
    return percentile_score("turnover_activity_daily", "ratio", td, float(row[1]))

def _fetch_price_strength_score(td: date) -> float | None: return percentile_score("ma_count_daily", "new_high_252d_pct", td, _fetch_col("msi_ma_count_daily", "new_high_252d_pct", td)) if _fetch_col("msi_ma_count_daily", "new_high_252d_pct", td) is not None else None

def _fetch_risk_appetite_score(td: date) -> float | None: return percentile_score("risk_appetite_daily", "spread_weighted", td, _fetch_col("msi_risk_appetite_daily", "spread_weighted", td)) if _fetch_col("msi_risk_appetite_daily", "spread_weighted", td) is not None else None

def _fetch_breadth_score(td: date) -> float | None: return percentile_score("ma_count_daily", "breadth_raw", td, _fetch_col("msi_ma_count_daily", "breadth_raw", td)) if _fetch_col("msi_ma_count_daily", "breadth_raw", td) is not None else None

def _fetch_limit_emotion_score(td: date) -> float | None: return _fetch_col("msi_limit_emotion_daily", "composite_score", td)

def _fetch_profit_effect_score(td: date) -> float | None: return percentile_score("profit_effect_daily", "score", td, _fetch_col("msi_profit_effect_daily", "score", td)) if _fetch_col("msi_profit_effect_daily", "score", td) is not None else None

def _fetch_sector_breadth_score(td: date) -> float | None:
    v = _fetch_col("msi_sector_breadth_daily", "advance_pct", td)
    return round(float(v) * 100, 2) if v is not None else None

def _fetch_style_risk_score(td: date) -> float | None: return percentile_score("style_risk_appetite_daily", "spread", td, _fetch_col("msi_style_risk_daily", "spread", td)) if _fetch_col("msi_style_risk_daily", "spread", td) is not None else None

_COMPONENT_FETCHERS = {"vol": _fetch_vol_score, "turnover": _fetch_turnover_score, "price_strength": _fetch_price_strength_score, "risk_appetite": _fetch_risk_appetite_score, "breadth": _fetch_breadth_score, "limit_emotion": _fetch_limit_emotion_score, "profit_effect": _fetch_profit_effect_score, "sector_breadth": _fetch_sector_breadth_score, "style_risk": _fetch_style_risk_score}


def _level(score: float) -> str:
    if score >= 70: return "hot"
    if score >= 55: return "active"
    if score >= 45: return "normal"
    if score >= 30: return "weak"
    return "ice"


def calc_market_sentiment_index(trade_date: date | str) -> dict[str, Any] | None:
    td = _to_date(trade_date)
    if td is None or not _is_valid_msi_trade_date(td):
        return None
    t0 = time.time()
    components: dict[str, float | None] = {}
    for key, fetcher in _COMPONENT_FETCHERS.items():
        try:
            components[key] = fetcher(td)
        except Exception:
            logger.debug("component %s fetch failed for %s", key, td, exc_info=True)
            components[key] = None
    present = [k for k, v in components.items() if v is not None]
    if not present:
        return None
    composite = round(sum(WEIGHTS[key] * (components[key] if components[key] is not None else _MISSING_SCORE) for key in WEIGHTS), 2)
    return {"tradeDate": td.isoformat(), "components": components, "compositeScore": composite, "componentCount": len(present), "level": _level(composite), "weights": dict(WEIGHTS), "elapsedMs": int((time.time() - t0) * 1000), "source": "composite"}


def save_market_sentiment_index(payload: dict) -> None:
    td = _to_date(payload.get("tradeDate"))
    if td is None:
        raise ValueError("payload.tradeDate required")
    if not _is_valid_msi_trade_date(td):
        logger.debug("save_market_sentiment_index skipped invalid/non-trading day: %s", td)
        return
    components = payload.get("components") or {}
    def _f(key: str) -> float | None:
        v = components.get(key)
        return float(v) if v is not None else None
    with session_scope() as db:
        execute_upsert(db, table="msi_index_daily", key_columns=["trade_date"], values={
            "trade_date": td,
            "vol_score": _f("vol"),
            "turnover_score": _f("turnover"),
            "price_strength_score": _f("price_strength"),
            "risk_appetite_score": _f("risk_appetite"),
            "breadth_score": _f("breadth"),
            "limit_emotion_score": _f("limit_emotion"),
            "profit_effect_score": _f("profit_effect"),
            "sector_breadth_score": _f("sector_breadth"),
            "style_risk_score": _f("style_risk"),
            "composite_score": float(payload.get("compositeScore") or 0),
            "component_count": int(payload.get("componentCount") or 0),
            "level": str(payload.get("level") or "normal"),
            "elapsed_ms": int(payload.get("elapsedMs") or 0),
            "source": str(payload.get("source") or "composite"),
            "ingested_at": __import__("datetime").datetime.now(),
        })


_MSI_COLS = ("trade_date", "vol_score", "turnover_score", "price_strength_score", "risk_appetite_score", "breadth_score", "limit_emotion_score", "profit_effect_score", "sector_breadth_score", "style_risk_score", "composite_score", "component_count", "level", "elapsed_ms", "source")
_MSI_SELECT = ", ".join(_MSI_COLS)


def _row_to_payload(row: tuple) -> dict:
    def _f(i: int) -> float | None:
        v = row[i]
        return float(v) if v is not None else None
    components = {"vol": _f(1), "turnover": _f(2), "price_strength": _f(3), "risk_appetite": _f(4), "breadth": _f(5), "limit_emotion": _f(6), "profit_effect": _f(7), "sector_breadth": _f(8), "style_risk": _f(9)}
    return {"tradeDate": row[0].isoformat(), "components": components, "weights": dict(WEIGHTS), "compositeScore": float(row[10]) if row[10] is not None else None, "componentCount": int(row[11]) if row[11] is not None else 0, "level": str(row[12]) if row[12] else "normal", "elapsedMs": int(row[13]) if row[13] is not None else None, "source": str(row[14]) if row[14] else "composite", "fromCache": True}


def get_market_sentiment_index(trade_date: date | str) -> dict | None:
    td = _to_date(trade_date)
    if td is None or not _is_valid_msi_trade_date(td):
        return None
    with session_scope() as db:
        row = db.execute(__import__("sqlalchemy").text(f"SELECT {_MSI_SELECT} FROM cynexus_appl_market.msi_index_daily WHERE trade_date = :td AND deleted_at IS NULL LIMIT 1"), {"td": td}).first()
    return _row_to_payload(row) if row else None


def get_market_sentiment_index_history(start: date | str, end: date | str | None = None) -> list[dict]:
    s = _to_date(start)
    e = _to_date(end) if end is not None else s
    if s is None or e is None:
        return []
    with session_scope() as db:
        rows = db.execute(__import__("sqlalchemy").text(f"SELECT {_MSI_SELECT} FROM cynexus_appl_market.msi_index_daily WHERE trade_date BETWEEN :s AND :e AND deleted_at IS NULL ORDER BY trade_date ASC"), {"s": s, "e": e}).all()
    return [_row_to_payload(r) for r in rows]


def calc_market_sentiment_index_cached(trade_date: date | str, *, force: bool = False) -> dict | None:
    if not force:
        cached = get_market_sentiment_index(trade_date)
        if cached is not None:
            return cached
    payload = calc_market_sentiment_index(trade_date)
    if payload is None:
        return None
    try:
        save_market_sentiment_index(payload)
    except Exception:
        logger.debug("save_market_sentiment_index failed (non-fatal): %s", payload.get("tradeDate"))
    return payload
