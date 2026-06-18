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
    """在 trade_date 算风格强弱.

    从 index_returns_daily 取沪深300 + 中证1000 的 window 日收益率,
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

    rows = con.execute(
        """
        SELECT index_code, index_name, return_pct, current, base_close
          FROM index_returns_daily
         WHERE trade_date = ? AND window_days = ?
           AND index_code IN (?, ?)
        """,
        [td, window, INDEX_CODES["hs300"], INDEX_CODES["csi1000"]],
    ).fetchall()

    if len(rows) < 2:
        return None

    hs300 = None
    csi1000 = None
    for code, name, return_pct, current, base_close in rows:
        item = {
            "name": name,
            "code": str(code),
            "returnPct": float(return_pct) if return_pct is not None else None,
            "current": float(current) if current is not None else None,
            "baseClose": float(base_close) if base_close is not None else None,
        }
        if str(code) == INDEX_CODES["hs300"]:
            hs300 = item
        elif str(code) == INDEX_CODES["csi1000"]:
            csi1000 = item

    if hs300 is None or csi1000 is None:
        return None

    hs300_ret = hs300["returnPct"]
    csi1000_ret = csi1000["returnPct"]
    spread = (csi1000_ret - hs300_ret) if (hs300_ret is not None and csi1000_ret is not None) else None

    elapsed_ms = int((time.time() - t0) * 1000)
    return {
        "tradeDate": td.isoformat(),
        "windowDays": window,
        "hs300": hs300,
        "csi1000": csi1000,
        "spread": round(spread, 4) if spread is not None else None,
        "elapsedMs": elapsed_ms,
        "source": "duckdb.index_returns_daily",
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
        str(payload.get("source") or "duckdb.index_returns_daily"),
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
        "source": str(row[6]) if row[6] else None,
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
    return [_row_to_payload(r) for r in rows]


# ---------------------------------------------------------------------------
# 4. cache-aside
# ---------------------------------------------------------------------------

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
            return cached
    payload = calc_style_risk_appetite(trade_date, window=window)
    if payload is None:
        return None
    try:
        save_style_risk_appetite(payload)
    except Exception:
        logger.debug("save_style_risk_appetite failed (non-fatal): %s", payload.get("tradeDate"))
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
