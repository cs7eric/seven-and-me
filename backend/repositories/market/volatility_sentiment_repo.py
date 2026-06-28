"""波动率情绪 (Volatility Sentiment) 仓储 — ClickHouse source + PostgreSQL cache."""
from __future__ import annotations

import math
import statistics
import time
from datetime import date
from typing import Any

from backend.adapters.market.clickhouse_store import query_rows
from backend.config.database import session_scope
from backend.repositories.market.market_pg_cynexus_repo import execute_upsert, to_date
from backend.services.stock.trading_calendar import is_trading_day

import logging
logger = logging.getLogger(__name__)

DEFAULT_UNDERLYING = {"code": "000300", "name": "沪深300", "full": "sh000300"}
DEFAULT_VOL_WINDOW = 20
DEFAULT_VOL_LOOKBACK = 252
_DEFAULT_PULL_LIMIT = 600


def _to_date(v: date | str | None) -> date | None:
    return to_date(v)


def _load_closes(full_code: str, td: date, n: int = _DEFAULT_PULL_LIMIT) -> list[tuple[date, float]]:
    rows = query_rows(
        """
        SELECT trade_date, close
          FROM index_daily_raw
         WHERE code = %s AND trade_date <= %s
         ORDER BY trade_date DESC
         LIMIT %s
        """,
        (full_code, td, n),
    )
    return [(r[0], float(r[1])) for r in reversed(rows)]


def _percentile_rank(current: float, history: list[float]) -> float:
    if not history:
        return 0.5
    return sum(1 for v in history if v <= current) / len(history)


def calc_volatility_sentiment(trade_date: date | str, *, underlying: dict[str, str] | None = None, window: int = DEFAULT_VOL_WINDOW, lookback: int = DEFAULT_VOL_LOOKBACK) -> dict[str, Any] | None:
    td = _to_date(trade_date)
    if td is None:
        return None
    u = underlying or DEFAULT_UNDERLYING
    window = max(2, min(window, 60))
    lookback = max(window + 1, min(lookback, 1000))
    t0 = time.time()
    bars = _load_closes(u["full"], td, n=lookback + window + 10)
    if len(bars) < window + 2:
        return None
    closes = [c for _, c in bars]
    dates = [d for d, _ in bars]
    returns: list[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        cur = closes[i]
        returns.append((cur - prev) / prev if prev > 0 else 0.0)
    vol_series: list[tuple[date, float]] = []
    for k in range(window, len(closes)):
        seg = returns[k - window:k]
        if len(seg) < 2:
            continue
        vol_series.append((dates[k], statistics.stdev(seg) * math.sqrt(252) * 100))
    if not vol_series or vol_series[-1][0] != td:
        return None
    current_date, current_vol = vol_series[-1]
    sample = [v for _, v in (vol_series[-lookback - 1:-1] if len(vol_series) >= lookback + 1 else vol_series[:-1])]
    percentile = _percentile_rank(current_vol, sample)
    score = round((1.0 - percentile) * 100.0, 2)
    return {
        "tradeDate": current_date.isoformat(),
        "underlyingCode": u["full"],
        "underlyingName": u["name"],
        "close": round(closes[-1], 4),
        "dailyReturnPct": round(returns[-1] * 100.0, 4) if returns else None,
        "realizedVol20d": round(current_vol, 2),
        "volWindowDays": window,
        "volLookbackDays": lookback,
        "percentile1y": round(percentile, 4),
        "sentimentScore": score,
        "sampleCount": len(sample),
        "elapsedMs": int((time.time() - t0) * 1000),
        "source": "clickhouse.index_daily_raw",
    }


def save_volatility_sentiment(payload: dict) -> None:
    td = _to_date(payload.get("tradeDate"))
    if td is None:
        raise ValueError("payload.tradeDate required")
    if not is_trading_day(td):
        logger.debug("save_volatility_sentiment skipped non-trading day: %s", td)
        return
    with session_scope() as db:
        execute_upsert(db, table="msi_volatility_daily", key_columns=["trade_date"], values={
            "trade_date": td,
            "underlying_code": str(payload.get("underlyingCode") or ""),
            "underlying_name": str(payload.get("underlyingName") or ""),
            "close": float(payload.get("close") or 0),
            "daily_return_pct": float(payload.get("dailyReturnPct")) if payload.get("dailyReturnPct") is not None else None,
            "realized_vol_20d": float(payload.get("realizedVol20d") or 0),
            "vol_window_days": int(payload.get("volWindowDays") or DEFAULT_VOL_WINDOW),
            "vol_lookback_days": int(payload.get("volLookbackDays") or DEFAULT_VOL_LOOKBACK),
            "percentile_1y": float(payload.get("percentile1y") or 0),
            "sentiment_score": float(payload.get("sentimentScore") or 0),
            "sample_count": int(payload.get("sampleCount") or 0),
            "elapsed_ms": int(payload.get("elapsedMs") or 0),
            "source": str(payload.get("source") or "clickhouse.index_daily_raw"),
            "ingested_at": __import__("datetime").datetime.now(),
        })


_VOL_SENTIMENT_COLS = ("trade_date", "underlying_code", "underlying_name", "close", "daily_return_pct", "realized_vol_20d", "vol_window_days", "vol_lookback_days", "percentile_1y", "sentiment_score", "sample_count", "elapsed_ms", "source")
_VOL_SENTIMENT_SELECT = ", ".join(_VOL_SENTIMENT_COLS)


def _row_to_payload(row: tuple) -> dict:
    daily_ret = float(row[4]) if row[4] is not None else None
    return {
        "tradeDate": row[0].isoformat(),
        "underlyingCode": str(row[1]),
        "underlyingName": str(row[2]),
        "close": float(row[3]) if row[3] is not None else None,
        "dailyReturnPct": daily_ret,
        "realizedVol20d": float(row[5]) if row[5] is not None else None,
        "volWindowDays": int(row[6]) if row[6] is not None else DEFAULT_VOL_WINDOW,
        "volLookbackDays": int(row[7]) if row[7] is not None else DEFAULT_VOL_LOOKBACK,
        "percentile1y": float(row[8]) if row[8] is not None else None,
        "sentimentScore": float(row[9]) if row[9] is not None else None,
        "sampleCount": int(row[10]) if row[10] is not None else 0,
        "elapsedMs": int(row[11]) if row[11] is not None else None,
        "source": str(row[12]),
        "fromCache": True,
    }


def get_volatility_sentiment(trade_date: date | str) -> dict | None:
    td = _to_date(trade_date)
    if td is None:
        return None
    with session_scope() as db:
        row = db.execute(__import__("sqlalchemy").text(f"SELECT {_VOL_SENTIMENT_SELECT} FROM cynexus_appl_market.msi_volatility_daily WHERE trade_date = :td AND deleted_at IS NULL LIMIT 1"), {"td": td}).first()
    return _row_to_payload(row) if row else None


def get_volatility_sentiment_history(start: date | str, end: date | str | None = None) -> list[dict]:
    s = _to_date(start)
    e = _to_date(end) if end is not None else s
    if s is None or e is None:
        return []
    with session_scope() as db:
        rows = db.execute(__import__("sqlalchemy").text(f"SELECT {_VOL_SENTIMENT_SELECT} FROM cynexus_appl_market.msi_volatility_daily WHERE trade_date BETWEEN :s AND :e AND deleted_at IS NULL ORDER BY trade_date ASC"), {"s": s, "e": e}).all()
    return [_row_to_payload(r) for r in rows]


def coverage() -> dict[str, Any]:
    with session_scope() as db:
        row = db.execute(__import__("sqlalchemy").text("SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM cynexus_appl_market.msi_volatility_daily WHERE deleted_at IS NULL")).one()
    return {"firstDate": row[0].isoformat() if row[0] else None, "lastDate": row[1].isoformat() if row[1] else None, "rowCount": int(row[2] or 0)}


def calc_volatility_sentiment_cached(trade_date: date | str, *, underlying: dict[str, str] | None = None, window: int = DEFAULT_VOL_WINDOW, lookback: int = DEFAULT_VOL_LOOKBACK, force: bool = False) -> dict | None:
    if not force:
        cached = get_volatility_sentiment(trade_date)
        if cached is not None:
            return cached
    payload = calc_volatility_sentiment(trade_date, underlying=underlying, window=window, lookback=lookback)
    if payload is None:
        return None
    try:
        save_volatility_sentiment(payload)
    except Exception:
        pass
    return payload
