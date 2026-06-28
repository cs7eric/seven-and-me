"""风格风险偏好 (Style Risk Appetite) 仓储 — ClickHouse source + PostgreSQL cache."""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

from backend.adapters.market.clickhouse_store import query_rows
from backend.config.database import session_scope
from backend.repositories.market.market_pg_cynexus_repo import execute_upsert, to_date
from backend.repositories.market.percentile_helper import enrich_history_scores, percentile_score

logger = logging.getLogger(__name__)
DEFAULT_WINDOW = 5
INDEX_CODES = {"hs300": "sh000300", "csi1000": "sh000852"}


def _to_date(v: date | str | None) -> date | None:
    return to_date(v)


def calc_style_risk_appetite(trade_date: date | str, *, window: int = DEFAULT_WINDOW) -> dict[str, Any] | None:
    td = _to_date(trade_date)
    if td is None:
        return None
    t0 = time.time()
    results: dict[str, dict[str, Any] | None] = {}
    for qfq_code, name, full_code in [("000300", "沪深300", INDEX_CODES["hs300"]), ("000852", "中证1000", INDEX_CODES["csi1000"])]:
        rows = query_rows(
            """
            SELECT trade_date, close
              FROM daily_qfq
             WHERE code = %s AND trade_date <= %s
             ORDER BY trade_date DESC
             LIMIT %s
            """,
            (qfq_code, td, window + 1),
        )
        if not rows or len(rows) < 2:
            results[full_code] = None
            continue
        rows_asc = list(reversed(rows))
        recent = rows_asc[-window:] if len(rows_asc) >= window else rows_asc
        current_close = float(recent[-1][1])
        base_close = float(recent[0][1])
        ret = (current_close - base_close) / base_close * 100 if base_close > 0 else None
        results[full_code] = {"name": name, "code": full_code, "returnPct": round(ret, 4) if ret is not None else None, "current": round(current_close, 4), "currentDate": recent[-1][0].isoformat(), "baseClose": round(base_close, 4), "baseDate": recent[0][0].isoformat()}

    hs300 = results.get(INDEX_CODES["hs300"])
    csi1000 = results.get(INDEX_CODES["csi1000"])
    if hs300 is None or csi1000 is None:
        return None
    hs300_ret = hs300["returnPct"]
    csi1000_ret = csi1000["returnPct"]
    if hs300_ret is None or csi1000_ret is None:
        return None
    spread = csi1000_ret - hs300_ret
    return {"tradeDate": td.isoformat(), "windowDays": window, "hs300": hs300, "csi1000": csi1000, "spread": round(spread, 4), "elapsedMs": int((time.time() - t0) * 1000), "source": "clickhouse.daily_qfq"}


def save_style_risk_appetite(payload: dict) -> None:
    td = _to_date(payload.get("tradeDate"))
    if td is None:
        raise ValueError("payload.tradeDate required")
    hs300 = payload.get("hs300") or {}
    csi1000 = payload.get("csi1000") or {}
    with session_scope() as db:
        execute_upsert(db, table="msi_style_risk_daily", key_columns=["trade_date"], values={
            "trade_date": td,
            "window_days": int(payload.get("windowDays") or DEFAULT_WINDOW),
            "hs300_return": float(hs300.get("returnPct") or 0),
            "csi1000_return": float(csi1000.get("returnPct") or 0),
            "spread": float(payload.get("spread") or 0),
            "elapsed_ms": int(payload.get("elapsedMs") or 0),
            "source": str(payload.get("source") or "clickhouse.daily_qfq"),
            "ingested_at": __import__("datetime").datetime.now(),
        })


_SRA_COLS = ("trade_date", "window_days", "hs300_return", "csi1000_return", "spread", "elapsed_ms", "source")
_SRA_SELECT = ", ".join(_SRA_COLS)


def _row_to_payload(row: tuple) -> dict:
    return {
        "tradeDate": row[0].isoformat(),
        "windowDays": int(row[1]) if row[1] is not None else DEFAULT_WINDOW,
        "hs300": {"name": "沪深300", "code": "sh000300", "returnPct": float(row[2]) if row[2] is not None else None},
        "csi1000": {"name": "中证1000", "code": "sh000852", "returnPct": float(row[3]) if row[3] is not None else None},
        "spread": float(row[4]) if row[4] is not None else None,
        "elapsedMs": int(row[5]) if row[5] is not None else None,
        "source": str(row[6]) if row[6] else "clickhouse.daily_qfq",
        "fromCache": True,
    }


def get_style_risk_appetite(trade_date: date | str) -> dict | None:
    td = _to_date(trade_date)
    if td is None:
        return None
    with session_scope() as db:
        row = db.execute(__import__("sqlalchemy").text(f"SELECT {_SRA_SELECT} FROM cynexus_appl_market.msi_style_risk_daily WHERE trade_date = :td AND deleted_at IS NULL LIMIT 1"), {"td": td}).first()
    return _row_to_payload(row) if row else None


def get_style_risk_appetite_history(start: date | str, end: date | str | None = None) -> list[dict]:
    s = _to_date(start)
    e = _to_date(end) if end is not None else s
    if s is None or e is None:
        return []
    with session_scope() as db:
        rows = db.execute(__import__("sqlalchemy").text(f"SELECT {_SRA_SELECT} FROM cynexus_appl_market.msi_style_risk_daily WHERE trade_date BETWEEN :s AND :e AND deleted_at IS NULL ORDER BY trade_date ASC"), {"s": s, "e": e}).all()
    items = [_row_to_payload(r) for r in rows]
    enrich_history_scores(items, "style_risk_appetite_daily", "spread", e)
    return items


def _add_score(payload: dict, trade_date: date | str) -> None:
    spread = payload.get("spread")
    if spread is not None:
        payload["score"] = percentile_score("style_risk_appetite_daily", "spread", trade_date, spread)
        payload["rawValue"] = spread


def calc_style_risk_appetite_cached(trade_date: date | str, *, window: int = DEFAULT_WINDOW, force: bool = False) -> dict | None:
    if not force:
        cached = get_style_risk_appetite(trade_date)
        if cached is not None:
            _add_score(cached, trade_date)
            return cached
    payload = calc_style_risk_appetite(trade_date, window=window)
    if payload is None:
        return None
    try:
        save_style_risk_appetite(payload)
    except Exception:
        logger.debug("save_style_risk_appetite failed (non-fatal): %s", payload.get("tradeDate"))
    _add_score(payload, trade_date)
    return payload
