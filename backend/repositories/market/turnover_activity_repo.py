"""成交活跃度 (Turnover Activity) 仓储 — ClickHouse source + PostgreSQL cache."""
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
SH_INDEX_CODE = "999999"
SZ_INDEX_CODE = "399001"


def _to_date(v: date | str | None) -> date | None:
    return to_date(v)


def _index_amount_rows_up_to(trade_date: date, *, limit_days: int) -> list[tuple]:
    return query_rows(
        """
        SELECT trade_date,
               sumIf(amount, code = %s) AS sh_amount,
               sumIf(amount, code = %s) AS sz_amount,
               (sumIf(amount, code = %s) + sumIf(amount, code = %s)) / 100000000.0 AS total_amount_yi
          FROM daily_raw
         WHERE trade_date <= %s AND code IN (%s, %s)
         GROUP BY trade_date
         HAVING countDistinct(code) = 2
         ORDER BY trade_date DESC
         LIMIT %s
        """,
        (SH_INDEX_CODE, SZ_INDEX_CODE, SH_INDEX_CODE, SZ_INDEX_CODE, trade_date, SH_INDEX_CODE, SZ_INDEX_CODE, limit_days),
    )


def get_turnover_activity_source_dates(start: date | str, end: date | str) -> list[date]:
    s = _to_date(start)
    e = _to_date(end)
    if s is None or e is None or s > e:
        return []
    rows = query_rows(
        """
        SELECT trade_date
          FROM daily_raw
         WHERE trade_date BETWEEN %s AND %s AND code IN (%s, %s)
         GROUP BY trade_date
        HAVING countDistinct(code) = 2
         ORDER BY trade_date ASC
        """,
        (s, e, SH_INDEX_CODE, SZ_INDEX_CODE),
    )
    return [r[0] for r in rows]


def get_turnover_activity_source_coverage() -> dict[str, date | None]:
    row = query_rows(
        """
        SELECT min(trade_date), max(trade_date), count(*)
          FROM (
                SELECT trade_date
                  FROM daily_raw
                 WHERE code IN (%s, %s)
                 GROUP BY trade_date
                HAVING countDistinct(code) = 2
               ) t
        """,
        (SH_INDEX_CODE, SZ_INDEX_CODE),
    )[0]
    return {"firstDate": row[0], "lastDate": row[1], "rowCount": int(row[2] or 0)}


def calc_turnover_activity(trade_date: date | str, *, window: int = DEFAULT_WINDOW) -> dict[str, Any] | None:
    td = _to_date(trade_date)
    if td is None:
        return None
    t0 = time.time()
    rows = _index_amount_rows_up_to(td, limit_days=window + 10)
    if not rows:
        return None
    rows_asc = list(reversed(rows))
    today_row = rows_asc[-1]
    today_total = float(today_row[3])
    today_sh_amount = float(today_row[1]) / 1e8
    today_sz_amount = float(today_row[2]) / 1e8
    prev = rows_asc[:-1]
    if not prev:
        return None
    sample = prev[-window:]
    if not sample:
        return None
    avg_20d = sum(float(r[3]) for r in sample) / len(sample)
    ratio = today_total / avg_20d if avg_20d > 0 else 0.0
    return {"tradeDate": td.isoformat(), "totalAmount": round(today_total, 2), "shAmount": round(today_sh_amount, 2), "szAmount": round(today_sz_amount, 2), "avg20dAmount": round(avg_20d, 2), "ratio": round(ratio, 4), "sampleCount": len(sample), "elapsedMs": int((time.time() - t0) * 1000), "source": "clickhouse.daily_raw.999999+399001"}


def save_turnover_activity(payload: dict) -> None:
    td = _to_date(payload.get("TradeDate") or payload.get("tradeDate"))
    if td is None:
        raise ValueError("payload.tradeDate required")
    if not is_trading_day(td):
        logger.debug("save_turnover_activity skipped non-trading day: %s", td)
        return
    with session_scope() as db:
        execute_upsert(db, table="msi_turnover_activity_daily", key_columns=["trade_date"], values={
            "trade_date": td,
            "total_amount": float(payload.get("totalAmount") or 0),
            "avg_20d_amount": float(payload.get("avg20dAmount") or 0),
            "ratio": float(payload.get("ratio") or 0),
            "score": float(payload.get("score")) if payload.get("score") is not None else None,
            "elapsed_ms": int(payload.get("elapsedMs") or 0),
            "source": str(payload.get("source") or "clickhouse.daily_raw.999999+399001"),
            "ingested_at": __import__("datetime").datetime.now(),
        })


_TA_COLS = ("trade_date", "total_amount", "avg_20d_amount", "ratio", "score", "elapsed_ms", "source")
_TA_SELECT = ", ".join(_TA_COLS)


def _row_to_payload(row: tuple) -> dict:
    return {"tradeDate": row[0].isoformat(), "totalAmount": float(row[1]) if row[1] is not None else None, "avg20dAmount": float(row[2]) if row[2] is not None else None, "ratio": float(row[3]) if row[3] is not None else None, "score": float(row[4]) if row[4] is not None else None, "elapsedMs": int(row[5]) if row[5] is not None else None, "source": str(row[6]), "fromCache": True}


def get_turnover_activity(trade_date: date | str) -> dict | None:
    td = _to_date(trade_date)
    if td is None:
        return None
    with session_scope() as db:
        row = db.execute(__import__("sqlalchemy").text(f"SELECT {_TA_SELECT} FROM cynexus_appl_market.msi_turnover_activity_daily WHERE trade_date = :td AND deleted_at IS NULL LIMIT 1"), {"td": td}).first()
    return _row_to_payload(row) if row else None


def get_turnover_activity_history(start: date | str, end: date | str | None = None) -> list[dict]:
    s = _to_date(start)
    e = _to_date(end) if end is not None else s
    if s is None or e is None:
        return []
    with session_scope() as db:
        rows = db.execute(__import__("sqlalchemy").text(f"SELECT {_TA_SELECT} FROM cynexus_appl_market.msi_turnover_activity_daily WHERE trade_date BETWEEN :s AND :e AND deleted_at IS NULL ORDER BY trade_date ASC"), {"s": s, "e": e}).all()
    items = [_row_to_payload(r) for r in rows]
    enrich_history_scores(items, "turnover_activity_daily", "ratio", e)
    return items


def coverage() -> dict[str, Any]:
    with session_scope() as db:
        row = db.execute(__import__("sqlalchemy").text("SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM cynexus_appl_market.msi_turnover_activity_daily WHERE deleted_at IS NULL")).one()
    return {"firstDate": row[0].isoformat() if row[0] else None, "lastDate": row[1].isoformat() if row[1] else None, "rowCount": int(row[2] or 0)}


def _add_score(payload: dict, trade_date: date | str) -> None:
    ratio = payload.get("ratio")
    if ratio is not None:
        payload["score"] = percentile_score("turnover_activity_daily", "ratio", trade_date, ratio)
        payload["rawValue"] = ratio


def calc_turnover_activity_cached(trade_date: date | str, *, window: int = DEFAULT_WINDOW, force: bool = False) -> dict | None:
    if not force:
        cached = get_turnover_activity(trade_date)
        if cached is not None:
            if cached.get("score") is None:
                _add_score(cached, trade_date)
                try:
                    with session_scope() as db:
                        db.execute(__import__("sqlalchemy").text("UPDATE cynexus_appl_market.msi_turnover_activity_daily SET score = :score WHERE trade_date = :td AND deleted_at IS NULL"), {"score": float(cached["score"]), "td": _to_date(trade_date)})
                except Exception:
                    logger.debug("backfill score for %s failed (non-fatal)", trade_date)
            else:
                if cached.get("ratio") is not None:
                    cached.setdefault("rawValue", cached["ratio"])
            return cached
    payload = calc_turnover_activity(trade_date, window=window)
    if payload is None:
        return None
    _add_score(payload, trade_date)
    try:
        save_turnover_activity(payload)
    except Exception:
        logger.debug("save_turnover_activity failed (non-fatal): %s", payload.get("tradeDate"))
    return payload
