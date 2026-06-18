"""风格风险偏好 (Style Risk Appetite) 仓储.

核心指标:
  spread = 中证1000 近 N 日收益率 - 沪深300 近 N 日收益率

含义:
  spread > 0: 小盘股相对大盘股更强 → 市场风险偏好更积极
  spread < 0: 大盘股相对更强 → 避险倾向

数据源: duckdb.index_returns_daily (已由 ma_count_scheduler 每日 17:06 更新)
落盘: duckdb.style_risk_appetite_daily (INSERT OR REPLACE by trade_date)
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

from backend.adapters.market.duckdb_store import get_conn
from backend.repositories.market.percentile_helper import (
    enrich_history_scores,
    percentile_score,
)

logger = logging.getLogger(__name__)

DEFAULT_WINDOW = 5
INDEX_CODES = {
    "hs300": "sh000300",
    "csi1000": "sh000852",
}


def _to_date(v: date | str | None) -> date | None:
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(v)


# ---------------------------------------------------------------------------
# 1. 计算
# ---------------------------------------------------------------------------

def calc_style_risk_appetite(
    trade_date: date | str,
    *,
    window: int = DEFAULT_WINDOW,
) -> dict[str, Any] | None:
    """在 trade_date 算风格强弱, 直接读 daily_qfq (TDX).

    从 daily_qfq 取沪深300(000300) + 中证1000(000852) 的 window 日收益率,
    spread = csi1000_return - hs300_return.

    Returns:
      {"tradeDate", "windowDays",
       "hs300": {"name", "code", "returnPct", "current", "baseClose"},
       "csi1000": {"name", "code", "returnPct", "current", "baseClose"},
       "spread", "elapsedMs"}
      无数据返 None.
    """
    td = _to_date(trade_date)
    if td is None:
        return None
    t0 = time.time()
    con = get_conn()

    codes_info: list[tuple[str, str, str]] = [
        ("000300", "沪深300", INDEX_CODES["hs300"]),
        ("000852", "中证1000", INDEX_CODES["csi1000"]),
    ]

    results: dict[str, dict[str, Any] | None] = {}
    for qfq_code, name, full_code in codes_info:
        rows = con.execute(
            """
            SELECT trade_date, close
              FROM daily_qfq
             WHERE code = ? AND trade_date <= ?
             ORDER BY trade_date DESC
             LIMIT ?
            """,
            [qfq_code, td, window + 1],
        ).fetchall()

        if not rows or len(rows) < 2:
            results[full_code] = None
            continue

        rows_asc = list(reversed(rows))
        recent = rows_asc[-window:] if len(rows_asc) >= window else rows_asc
        current_close = float(recent[-1][1])
        current_date = recent[-1][0]
        base_close = float(recent[0][1])
        base_date = recent[0][0]
        ret = (current_close - base_close) / base_close * 100 if base_close > 0 else None

        results[full_code] = {
            "name": name,
            "code": full_code,
            "returnPct": round(ret, 4) if ret is not None else None,
            "current": round(current_close, 4),
            "currentDate": current_date.isoformat(),
            "baseClose": round(base_close, 4),
            "baseDate": base_date.isoformat(),
        }

    hs300 = results.get(INDEX_CODES["hs300"])
    csi1000 = results.get(INDEX_CODES["csi1000"])

    if hs300 is None or csi1000 is None:
        return None
    hs300_ret = hs300["returnPct"]
    csi1000_ret = csi1000["returnPct"]
    if hs300_ret is None or csi1000_ret is None:
        return None

    spread = csi1000_ret - hs300_ret

    elapsed_ms = int((time.time() - t0) * 1000)
    return {
        "tradeDate": td.isoformat(),
        "windowDays": window,
        "hs300": hs300,
        "csi1000": csi1000,
        "spread": round(spread, 4),
        "elapsedMs": elapsed_ms,
        "source": "duckdb.daily_qfq",
    }


# ---------------------------------------------------------------------------
# 2. 落盘
# ---------------------------------------------------------------------------

def save_style_risk_appetite(payload: dict) -> None:
    """把 calc_style_risk_appetite 的 dict 落盘 (INSERT OR REPLACE by trade_date)."""
    td = _to_date(payload.get("tradeDate"))
    if td is None:
        raise ValueError("payload.tradeDate required")
    hs300 = payload.get("hs300") or {}
    csi1000 = payload.get("csi1000") or {}
    con = get_conn()
    con.execute("""
        INSERT OR REPLACE INTO style_risk_appetite_daily
            (trade_date, window_days,
             hs300_return, csi1000_return, spread,
             elapsed_ms, source, ingested_at)
        VALUES (?, ?,
                ?, ?, ?,
                ?, ?, current_timestamp)
    """, [
        td,
        int(payload.get("windowDays") or DEFAULT_WINDOW),
        float(hs300.get("returnPct") or 0),
        float(csi1000.get("returnPct") or 0),
        float(payload.get("spread") or 0),
        int(payload.get("elapsedMs") or 0),
        str(payload.get("source") or "duckdb.daily_qfq"),
    ])


# ---------------------------------------------------------------------------
# 3. 读
# ---------------------------------------------------------------------------

_SRA_COLS = (
    "trade_date", "window_days",
    "hs300_return", "csi1000_return", "spread",
    "elapsed_ms", "source",
)
_SRA_SELECT = ", ".join(_SRA_COLS)


def _row_to_payload(row: tuple) -> dict:
    return {
        "tradeDate": row[0].isoformat(),
        "windowDays": int(row[1]) if row[1] is not None else DEFAULT_WINDOW,
        "hs300": {
            "name": "沪深300",
            "code": "sh000300",
            "returnPct": float(row[2]) if row[2] is not None else None,
        },
        "csi1000": {
            "name": "中证1000",
            "code": "sh000852",
            "returnPct": float(row[3]) if row[3] is not None else None,
        },
        "spread": float(row[4]) if row[4] is not None else None,
        "elapsedMs": int(row[5]) if row[5] is not None else None,
        "source": str(row[6]) if row[6] else "duckdb.daily_qfq",
        "fromCache": True,
    }


def get_style_risk_appetite(trade_date: date | str) -> dict | None:
    """按日期查 style_risk_appetite_daily. 无记录返 None (不抛)."""
    td = _to_date(trade_date)
    if td is None:
        return None
    con = get_conn()
    r = con.execute(
        f"SELECT {_SRA_SELECT} FROM style_risk_appetite_daily WHERE trade_date = ?",
        [td],
    ).fetchone()
    return _row_to_payload(r) if r else None


def get_style_risk_appetite_history(
    start: date | str,
    end: date | str | None = None,
) -> list[dict]:
    """区间查 style_risk_appetite_daily (按 trade_date ASC)."""
    s = _to_date(start)
    e = _to_date(end) if end is not None else s
    if s is None or e is None:
        return []
    con = get_conn()
    rows = con.execute(
        f"SELECT {_SRA_SELECT} FROM style_risk_appetite_daily "
        f"WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date ASC",
        [s, e],
    ).fetchall()
    items = [_row_to_payload(r) for r in rows]
    enrich_history_scores(items, "style_risk_appetite_daily", "spread", e)
    return items


# ---------------------------------------------------------------------------
# 4. cache-aside
# ---------------------------------------------------------------------------

def _add_score(payload: dict, trade_date: date | str) -> None:
    """给 payload 加 score (0-100 历史分位) + rawValue."""
    spread = payload.get("spread")
    if spread is not None:
        payload["score"] = percentile_score(
            "style_risk_appetite_daily", "spread", trade_date, spread,
        )
        payload["rawValue"] = spread


def calc_style_risk_appetite_cached(
    trade_date: date | str,
    *,
    window: int = DEFAULT_WINDOW,
    force: bool = False,
) -> dict | None:
    """cache-aside: 优先查表, 没记录才现算 + 自动落盘."""
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


# ---------------------------------------------------------------------------
# smoke
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json as _json
    print("=== coverage ===")
    from backend.adapters.market.duckdb_store import get_conn
    con = get_conn()
    r = con.execute(
        "SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM style_risk_appetite_daily"
    ).fetchone()
    print(f"  first={r[0]} last={r[1]} count={r[2]}")

    print("\n=== calc_style_risk_appetite(2026-06-17) ===")
    r = calc_style_risk_appetite("2026-06-17")
    if r:
        print(_json.dumps(r, indent=2, ensure_ascii=False, default=str))

    print("\n=== calc_style_risk_appetite_cached(2026-06-17) ===")
    r = calc_style_risk_appetite_cached("2026-06-17")
    if r:
        print(_json.dumps(r, indent=2, ensure_ascii=False, default=str))
