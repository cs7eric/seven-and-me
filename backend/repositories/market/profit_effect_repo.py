"""赚钱效应 (Profit Effect) 仓储.

核心指标:
  score = 60% × 近5日上涨占比 + 40% × (100 - 60日新低占比)

含义:
  看大多数股票最近有没有赚钱。近 5 日上涨面越宽、新低越少 → 赚钱效应越好.

数据源: duckdb.ma_count_daily (up_5d_pct, new_low_60d_pct)
落盘: duckdb.profit_effect_daily (INSERT OR REPLACE by trade_date)
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

from backend.adapters.market.duckdb_store import conn, get_conn
from backend.repositories.market.percentile_helper import (
    enrich_history_scores,
    percentile_score,
)
from backend.services.stock.trading_calendar import is_trading_day

logger = logging.getLogger(__name__)


def _to_date(v: date | str | None) -> date | None:
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(v)


def _pct(num: float, den: float) -> float:
    return round(num / den * 100, 2) if den > 0 else 0.0


# ---------------------------------------------------------------------------
# 1. 计算
# ---------------------------------------------------------------------------

def calc_profit_effect(trade_date: date | str) -> dict[str, Any] | None:
    """在 trade_date 算赚钱效应.

    从 ma_count_daily 取 up_5d_pct + new_low_60d_pct,
    score = 0.60 × up_5d_pct + 0.40 × (100 - new_low_60d_pct)

    Returns:
      {"tradeDate", "up5dPct", "newLow60dPct", "score", "elapsedMs"}
      无数据返 None.
    """
    td = _to_date(trade_date)
    if td is None:
        return None
    t0 = time.time()
    con = get_conn()
    row = con.execute(
        "SELECT up_5d_pct, new_low_60d_pct FROM ma_count_daily WHERE trade_date = ?",
        [td],
    ).fetchone()
    if not row:
        return None

    up5d_pct = float(row[0]) if row[0] is not None else 0
    new_low_pct = float(row[1]) if row[1] is not None else 0

    # 60日新低反向得分 = 100 - new_low_60d_pct (新低越少=分越高)
    score = round(0.60 * up5d_pct + 0.40 * (100 - new_low_pct), 2)

    elapsed_ms = int((time.time() - t0) * 1000)
    return {
        "tradeDate": td.isoformat(),
        "up5dPct": up5d_pct,
        "newLow60dPct": new_low_pct,
        "score": score,
        "elapsedMs": elapsed_ms,
        "source": "duckdb.ma_count_daily",
    }


# ---------------------------------------------------------------------------
# 2. 落盘
# ---------------------------------------------------------------------------

def save_profit_effect(payload: dict) -> None:
    """INSERT OR REPLACE by trade_date. 非交易日拒绝落盘."""
    td = _to_date(payload.get("tradeDate"))
    if td is None:
        raise ValueError("payload.tradeDate required")
    if not is_trading_day(td):
        logger.debug("save_profit_effect skipped non-trading day: %s", td)
        return
    con = get_conn()
    con.execute("""
        INSERT OR REPLACE INTO profit_effect_daily
            (trade_date, up_5d_pct, new_low_60d_pct, score,
             elapsed_ms, source, ingested_at)
        VALUES (?, ?, ?, ?,
                ?, ?, current_timestamp)
    """, [
        td,
        float(payload.get("up5dPct") or 0),
        float(payload.get("newLow60dPct") or 0),
        float(payload.get("score") or 0),
        int(payload.get("elapsedMs") or 0),
        str(payload.get("source") or "duckdb.ma_count_daily"),
    ])


# ---------------------------------------------------------------------------
# 3. 读
# ---------------------------------------------------------------------------

_PE_COLS = (
    "trade_date", "up_5d_pct", "new_low_60d_pct", "score",
    "elapsed_ms", "source",
)
_PE_SELECT = ", ".join(_PE_COLS)


def _row_to_payload(row: tuple) -> dict:
    return {
        "tradeDate": row[0].isoformat(),
        "up5dPct": float(row[1]) if row[1] is not None else None,
        "newLow60dPct": float(row[2]) if row[2] is not None else None,
        "score": float(row[3]) if row[3] is not None else None,
        "elapsedMs": int(row[4]) if row[4] is not None else None,
        "source": str(row[5]) if row[5] else None,
        "fromCache": True,
    }


def get_profit_effect(trade_date: date | str) -> dict | None:
    td = _to_date(trade_date)
    if td is None:
        return None
    with conn() as con:
        r = con.execute(
            f"SELECT {_PE_SELECT} FROM profit_effect_daily WHERE trade_date = ?",
            [td],
        ).fetchone()
    return _row_to_payload(r) if r else None


def get_profit_effect_history(
    start: date | str,
    end: date | str | None = None,
) -> list[dict]:
    s = _to_date(start)
    e = _to_date(end) if end is not None else s
    if s is None or e is None:
        return []
    with conn() as con:
        rows = con.execute(
            f"SELECT {_PE_SELECT} FROM profit_effect_daily "
            f"WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date ASC",
            [s, e],
        ).fetchall()
    items = [_row_to_payload(r) for r in rows]
    enrich_history_scores(items, "profit_effect_daily", "score", e)
    return items


# ---------------------------------------------------------------------------
# 4. cache-aside
# ---------------------------------------------------------------------------

def _add_score(payload: dict, trade_date: date | str) -> None:
    """给 payload 加 score (0-100 历史分位) + rawValue (原始 score)."""
    raw = payload.get("score")
    if raw is not None:
        payload["score"] = percentile_score(
            "profit_effect_daily", "score", trade_date, raw,
        )
        payload["rawValue"] = raw


def calc_profit_effect_cached(
    trade_date: date | str,
    *,
    force: bool = False,
) -> dict | None:
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


# ---------------------------------------------------------------------------
# smoke
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json as _json
    from backend.adapters.market.duckdb_store import get_conn
    con = get_conn()
    r = con.execute(
        "SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM profit_effect_daily"
    ).fetchone()
    print(f"coverage: first={r[0]} last={r[1]} count={r[2]}")
    print("\n=== calc_profit_effect(2026-06-17) ===")
    r = calc_profit_effect("2026-06-17")
    if r:
        print(_json.dumps(r, indent=2, ensure_ascii=False))
