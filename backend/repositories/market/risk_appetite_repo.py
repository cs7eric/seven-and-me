"""风险偏好 (Risk Appetite) 仓储 — ClickHouse source + PostgreSQL cache."""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

from backend.adapters.market.clickhouse_store import query_rows
from backend.config.database import session_scope
from backend.repositories.market.market_pg_cynexus_repo import execute_upsert, to_date
from backend.repositories.market.percentile_helper import enrich_history_scores, percentile_score
from backend.services.stock.trading_calendar import is_trading_day

logger = logging.getLogger(__name__)
DEFAULT_WINDOW = 20
TREASURY_WEIGHTS = {"511010": 0.5, "511090": 0.5}


def _to_date(v: date | str | None) -> date | None:
    return to_date(v)


def _calc_return_for_code(code: str, td: date, window: int) -> dict:
    rows = query_rows(
        """
        SELECT trade_date, close
          FROM daily_qfq
         WHERE code = %s AND trade_date <= %s
         ORDER BY trade_date DESC
         LIMIT %s
        """,
        (code, td, window + 1),
    )
    if not rows or len(rows) < 2:
        return {"close": None, "currentDate": None, "baseClose": None, "baseDate": None, "returnPct": None, "barsUsed": len(rows)}
    rows = list(reversed(rows))
    recent = rows[-window:] if len(rows) >= window else rows
    current_close = float(recent[-1][1])
    base_close = float(recent[0][1])
    ret = (current_close - base_close) / base_close * 100 if base_close > 0 else None
    return {
        "close": round(current_close, 4),
        "currentDate": recent[-1][0].isoformat(),
        "baseClose": round(base_close, 4),
        "baseDate": recent[0][0].isoformat(),
        "returnPct": round(ret, 4) if ret is not None else None,
        "barsUsed": len(recent),
    }


def calc_risk_appetite(trade_date: date | str, window: int = DEFAULT_WINDOW) -> dict[str, Any]:
    td = _to_date(trade_date)
    assert td is not None
    window = max(2, min(window, 250))
    t0 = time.time()
    hs = _calc_return_for_code("000300", td, window)
    t1 = _calc_return_for_code("511010", td, window)
    t2 = _calc_return_for_code("511090", td, window)

    hs_ret = hs["returnPct"]
    t1_ret = t1["returnPct"]
    t2_ret = t2["returnPct"]
    weighted_ret: float | None = None
    if t1_ret is not None and t2_ret is not None:
        weighted_ret = round(t1_ret * TREASURY_WEIGHTS["511010"] + t2_ret * TREASURY_WEIGHTS["511090"], 4)
    elif t1_ret is not None:
        weighted_ret = t1_ret
    elif t2_ret is not None:
        weighted_ret = t2_ret

    def spread(a: float | None, b: float | None) -> float | None:
        return round(a - b, 4) if a is not None and b is not None else None

    return {
        "tradeDate": td.isoformat(),
        "windowDays": window,
        "hs300": hs,
        "treasury": {
            "511010": {**t1, "weight": TREASURY_WEIGHTS["511010"]},
            "511090": {**t2, "weight": TREASURY_WEIGHTS["511090"]},
            "weighted": {"returnPct": weighted_ret},
        },
        "spread": {"511010": spread(hs_ret, t1_ret), "511090": spread(hs_ret, t2_ret), "weighted": spread(hs_ret, weighted_ret)},
        "elapsedMs": int((time.time() - t0) * 1000),
        "source": "clickhouse.daily_qfq",
    }


def save_risk_appetite(payload: dict) -> None:
    td = _to_date(payload.get("tradeDate"))
    if td is None:
        raise ValueError("payload.tradeDate required")
    if not is_trading_day(td):
        logger.debug("save_risk_appetite skipped non-trading day: %s", td)
        return
    spread = payload.get("spread") or {}
    hs = payload.get("hs300") or {}
    t = payload.get("treasury") or {}
    t1 = t.get("511010") or {}
    t2 = t.get("511090") or {}
    tw = (t.get("weighted") or {}).get("returnPct")
    with session_scope() as db:
        execute_upsert(db, table="msi_risk_appetite_daily", key_columns=["trade_date"], values={
            "trade_date": td,
            "hs300_close": float(hs.get("close") or 0),
            "hs300_base_close": float(hs.get("baseClose") or 0),
            "hs300_base_date": _to_date(hs.get("baseDate")) or td,
            "hs300_20d_return": float(hs.get("returnPct") or 0),
            "treasury_511010_close": t1.get("close"),
            "treasury_511010_base_close": t1.get("baseClose"),
            "treasury_511010_20d_return": t1.get("returnPct"),
            "treasury_511090_close": t2.get("close"),
            "treasury_511090_base_close": t2.get("baseClose"),
            "treasury_511090_20d_return": t2.get("returnPct"),
            "treasury_weighted_20d_return": float(tw if tw is not None else (hs.get("returnPct") or 0)),
            "spread_511010": float(spread.get("511010") or 0),
            "spread_511090": float(spread.get("511090") or 0),
            "spread_weighted": float(spread.get("weighted") or 0),
            "window_days": int(payload.get("windowDays") or DEFAULT_WINDOW),
            "source": str(payload.get("source") or "clickhouse.daily_qfq"),
            "elapsed_ms": int(payload.get("elapsedMs") or 0),
            "ingested_at": __import__("datetime").datetime.now(),
        })


_RISK_APPETITE_COLS = (
    "trade_date", "hs300_close", "hs300_base_close", "hs300_base_date", "hs300_20d_return",
    "treasury_511010_close", "treasury_511010_base_close", "treasury_511010_20d_return",
    "treasury_511090_close", "treasury_511090_base_close", "treasury_511090_20d_return",
    "treasury_weighted_20d_return",
    "spread_511010", "spread_511090", "spread_weighted",
    "window_days", "source", "elapsed_ms",
)
_RISK_APPETITE_SELECT = ", ".join(_RISK_APPETITE_COLS)


def _row_to_payload(row: tuple) -> dict:
    return {
        "tradeDate": row[0].isoformat(),
        "windowDays": int(row[15]) if row[15] is not None else DEFAULT_WINDOW,
        "hs300": {"close": float(row[1]) if row[1] is not None else None, "currentDate": row[0].isoformat(), "baseClose": float(row[2]) if row[2] is not None else None, "baseDate": row[3].isoformat() if row[3] else None, "returnPct": float(row[4]) if row[4] is not None else None},
        "treasury": {
            "511010": {"close": float(row[5]) if row[5] is not None else None, "currentDate": row[0].isoformat(), "baseClose": float(row[6]) if row[6] is not None else None, "baseDate": None, "returnPct": float(row[7]) if row[7] is not None else None, "weight": TREASURY_WEIGHTS["511010"]},
            "511090": {"close": float(row[8]) if row[8] is not None else None, "currentDate": row[0].isoformat(), "baseClose": float(row[9]) if row[9] is not None else None, "baseDate": None, "returnPct": float(row[10]) if row[10] is not None else None, "weight": TREASURY_WEIGHTS["511090"]},
            "weighted": {"returnPct": float(row[11]) if row[11] is not None else None},
        },
        "spread": {"511010": float(row[12]) if row[12] is not None else None, "511090": float(row[13]) if row[13] is not None else None, "weighted": float(row[14]) if row[14] is not None else None},
        "elapsedMs": int(row[17]) if row[17] is not None else None,
        "source": str(row[16]) if row[16] is not None else "clickhouse.daily_qfq",
        "fromCache": True,
    }


def get_risk_appetite(trade_date: date | str) -> dict | None:
    td = _to_date(trade_date)
    if td is None:
        return None
    with session_scope() as db:
        row = db.execute(__import__("sqlalchemy").text(f"SELECT {_RISK_APPETITE_SELECT} FROM cynexus_appl_market.msi_risk_appetite_daily WHERE trade_date = :td AND deleted_at IS NULL LIMIT 1"), {"td": td}).first()
    return _row_to_payload(row) if row else None


def get_risk_appetite_history(start: date | str, end: date | str | None = None) -> list[dict]:
    s = _to_date(start)
    e = _to_date(end) if end is not None else s
    if s is None or e is None:
        return []
    with session_scope() as db:
        rows = db.execute(__import__("sqlalchemy").text(f"SELECT {_RISK_APPETITE_SELECT} FROM cynexus_appl_market.msi_risk_appetite_daily WHERE trade_date BETWEEN :s AND :e AND deleted_at IS NULL ORDER BY trade_date ASC"), {"s": s, "e": e}).all()
    items = [_row_to_payload(r) for r in rows]
    enrich_history_scores(items, "risk_appetite_daily", "spread_weighted", e)
    return items


def _add_score(payload: dict, trade_date: date | str) -> None:
    spread = payload.get("spread", {}).get("weighted")
    if spread is not None:
        payload["score"] = percentile_score("risk_appetite_daily", "spread_weighted", trade_date, spread)
        payload["rawValue"] = spread


def calc_risk_appetite_cached(trade_date: date | str, *, window: int = DEFAULT_WINDOW, force: bool = False) -> dict:
    if not force:
        cached = get_risk_appetite(trade_date)
        if cached is not None:
            _add_score(cached, trade_date)
            return cached
    payload = calc_risk_appetite(trade_date, window=window)
    try:
        save_risk_appetite(payload)
    except Exception:
        pass
    _add_score(payload, trade_date)
    return payload
