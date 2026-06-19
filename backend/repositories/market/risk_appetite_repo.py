"""风险偏好 (Risk Appetite) 仓储.

公式: spread = 沪深300 20日累计收益 - 国债 ETF 20日累计收益
数据源: duckdb.daily_qfq
  - 沪深300: code='000300' (长历史 5200+ 行)
  - 上证国债ETF: code='511010'
  - 30年国债ETF: code='511090'
主指标: spread_weighted (沪深300 - (511010+511090)/2 的等权平均 treasury)
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
from backend.services.stock.trading_calendar import is_trading_day

logger = logging.getLogger(__name__)


# 风险偏好窗口 (默认 20 日, 对应 ~ 1 个月)
DEFAULT_WINDOW = 20

# ETF 权重 (50/50 等权)
TREASURY_WEIGHTS = {
    "511010": 0.5,
    "511090": 0.5,
}


def _to_date(v: date | str | None) -> date | None:
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(v)


def _calc_return_for_code(code: str, td: date, window: int) -> dict:
    """对单只 code 在 trade_date 算 window 日累计收益.

    取 <= td 的最近 window+1 个交易日 K 线 (含 base 日).
    若不足 window+1 行但有 ≥2 行, 用现有数据算 (fallback).

    Returns dict:
      {close, currentDate, baseClose, baseDate, returnPct, barsUsed}
      数据不足时各字段为 None.
    """
    con = get_conn()
    rows = con.execute(
        """
        SELECT trade_date, close
          FROM daily_qfq
         WHERE code = ? AND trade_date <= ?
         ORDER BY trade_date DESC
         LIMIT ?
        """,
        [code, td, window + 1],
    ).fetchall()
    if not rows or len(rows) < 2:
        return {"close": None, "currentDate": None, "baseClose": None,
                "baseDate": None, "returnPct": None, "barsUsed": len(rows)}
    rows = list(reversed(rows))  # ASC
    # 截取最近 window 个交易日 (base = rows[0], current = rows[-1])
    recent = rows[-window:] if len(rows) >= window else rows
    current_close = float(recent[-1][1])
    current_date = recent[-1][0]
    base_close = float(recent[0][1])
    base_date = recent[0][0]
    ret = (current_close - base_close) / base_close * 100 if base_close > 0 else None
    return {
        "close": round(current_close, 4),
        "currentDate": current_date.isoformat(),
        "baseClose": round(base_close, 4),
        "baseDate": base_date.isoformat(),
        "returnPct": round(ret, 4) if ret is not None else None,
        "barsUsed": len(recent),
    }


def calc_risk_appetite(trade_date: date | str, window: int = DEFAULT_WINDOW) -> dict[str, Any]:
    """算风险偏好 spread 在 trade_date (沪深300 - 国债 ETF 加权平均).

    Returns:
      {
        "tradeDate": "2026-06-16",
        "windowDays": 20,
        "hs300": {close, baseClose, baseDate, returnPct},
        "treasury": {
          "511010": {close, baseClose, baseDate, returnPct, weight},
          "511090": {close, baseClose, baseDate, returnPct, weight},
          "weighted": {returnPct}                # (r_511010 + r_511090) / 2
        },
        "spread": {
          "511010": 2.35,        # hs300 - 511010
          "511090": 2.10,        # hs300 - 511090
          "weighted": 2.22       # 主指标
        },
        "elapsedMs": 420,
        "source": "duckdb.daily_qfq"
      }
    """
    td = _to_date(trade_date)
    assert td is not None
    window = max(2, min(window, 250))  # 防止爆炸
    t0 = time.time()

    hs = _calc_return_for_code("000300", td, window)
    t1 = _calc_return_for_code("511010", td, window)
    t2 = _calc_return_for_code("511090", td, window)

    hs_ret = hs["returnPct"]
    t1_ret = t1["returnPct"]
    t2_ret = t2["returnPct"]

    # 加权 treasury 收益 (等权 0.5+0.5)
    weighted_ret: float | None = None
    if t1_ret is not None and t2_ret is not None:
        weighted_ret = round(
            t1_ret * TREASURY_WEIGHTS["511010"] + t2_ret * TREASURY_WEIGHTS["511090"],
            4,
        )
    elif t1_ret is not None:
        weighted_ret = t1_ret  # fallback
    elif t2_ret is not None:
        weighted_ret = t2_ret

    def spread(a: float | None, b: float | None) -> float | None:
        if a is None or b is None:
            return None
        return round(a - b, 4)

    elapsed_ms = int((time.time() - t0) * 1000)
    return {
        "tradeDate": td.isoformat(),
        "windowDays": window,
        "hs300": hs,
        "treasury": {
            "511010": {**t1, "weight": TREASURY_WEIGHTS["511010"]},
            "511090": {**t2, "weight": TREASURY_WEIGHTS["511090"]},
            "weighted": {"returnPct": weighted_ret},
        },
        "spread": {
            "511010": spread(hs_ret, t1_ret),
            "511090": spread(hs_ret, t2_ret),
            "weighted": spread(hs_ret, weighted_ret),
        },
        "elapsedMs": elapsed_ms,
        "source": "duckdb.daily_qfq",
    }


def save_risk_appetite(payload: dict) -> None:
    """把 calc_risk_appetite 的 dict 落盘 (INSERT OR REPLACE by trade_date).

    非交易日拒绝落盘 (历史上有 2026-06-13/14 端午调休脏数据).
    """
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

    con = get_conn()
    con.execute("""
        INSERT OR REPLACE INTO risk_appetite_daily
            (trade_date, hs300_close, hs300_base_close, hs300_base_date, hs300_20d_return,
             treasury_511010_close, treasury_511010_base_close, treasury_511010_20d_return,
             treasury_511090_close, treasury_511090_base_close, treasury_511090_20d_return,
             treasury_weighted_20d_return,
             spread_511010, spread_511090, spread_weighted,
             window_days, source, elapsed_ms, ingested_at)
        VALUES (?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?,
                ?, ?, ?,
                ?, ?, ?, current_timestamp)
    """, [
        td,
        float(hs.get("close") or 0),
        float(hs.get("baseClose") or 0),
        _to_date(hs.get("baseDate")) or td,
        float(hs.get("returnPct") or 0),
        # 511010 — 允许 None (写入 NULL 表示该 ETF 没数据)
        t1.get("close"),
        t1.get("baseClose"),
        t1.get("returnPct"),
        t2.get("close"),
        t2.get("baseClose"),
        t2.get("returnPct"),
        float(tw if tw is not None else (hs.get("returnPct") or 0)),  # 主 treasury fallback
        float(spread.get("511010") or 0),
        float(spread.get("511090") or 0),
        float(spread.get("weighted") or 0),
        int(payload.get("windowDays") or DEFAULT_WINDOW),
        str(payload.get("source") or "duckdb.daily_qfq"),
        int(payload.get("elapsedMs") or 0),
    ])


# 列顺序: 跟 SELECT 列表保持一致
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
    """duckdb 行 → calc_risk_appetite 同 shape dict.

    注意: 表里没存 baseDate / currentDate (为节省空间),
    返回时只给主指标 + spread, baseDate / currentDate 用 trade_date 兜底.
    """
    return {
        "tradeDate": row[0].isoformat(),
        "windowDays": int(row[15]) if row[15] is not None else DEFAULT_WINDOW,
        "hs300": {
            "close": float(row[1]) if row[1] is not None else None,
            "currentDate": row[0].isoformat(),  # 兜底 = trade_date
            "baseClose": float(row[2]) if row[2] is not None else None,
            "baseDate": row[3].isoformat() if row[3] else None,
            "returnPct": float(row[4]) if row[4] is not None else None,
        },
        "treasury": {
            "511010": {
                "close": float(row[5]) if row[5] is not None else None,
                "currentDate": row[0].isoformat(),
                "baseClose": float(row[6]) if row[6] is not None else None,
                "baseDate": None,
                "returnPct": float(row[7]) if row[7] is not None else None,
                "weight": TREASURY_WEIGHTS["511010"],
            },
            "511090": {
                "close": float(row[8]) if row[8] is not None else None,
                "currentDate": row[0].isoformat(),
                "baseClose": float(row[9]) if row[9] is not None else None,
                "baseDate": None,
                "returnPct": float(row[10]) if row[10] is not None else None,
                "weight": TREASURY_WEIGHTS["511090"],
            },
            "weighted": {"returnPct": float(row[11]) if row[11] is not None else None},
        },
        "spread": {
            "511010": float(row[12]) if row[12] is not None else None,
            "511090": float(row[13]) if row[13] is not None else None,
            "weighted": float(row[14]) if row[14] is not None else None,
        },
        "elapsedMs": int(row[17]) if row[17] is not None else None,
        "source": str(row[16]),
        "fromCache": True,
    }


def get_risk_appetite(trade_date: date | str) -> dict | None:
    """按日期查 risk_appetite_daily. 无记录返 None (不抛)."""
    td = _to_date(trade_date)
    if td is None:
        return None
    con = get_conn()
    r = con.execute(f"""
        SELECT {_RISK_APPETITE_SELECT}
          FROM risk_appetite_daily
         WHERE trade_date = ?
    """, [td]).fetchone()
    return _row_to_payload(r) if r else None


def get_risk_appetite_history(
    start: date | str,
    end: date | str | None = None,
) -> list[dict]:
    """区间查 risk_appetite_daily (按 trade_date ASC), 每条只含主指标 + 历史 sparkline 所需字段."""
    s = _to_date(start)
    e = _to_date(end) if end is not None else s
    if s is None or e is None:
        return []
    con = get_conn()
    rows = con.execute(f"""
        SELECT {_RISK_APPETITE_SELECT}
          FROM risk_appetite_daily
         WHERE trade_date BETWEEN ? AND ?
         ORDER BY trade_date ASC
    """, [s, e]).fetchall()
    items = [_row_to_payload(r) for r in rows]
    enrich_history_scores(items, "risk_appetite_daily", "spread_weighted", e)
    return items


def _add_score(payload: dict, trade_date: date | str) -> None:
    """给 payload 加 score (0-100 历史分位) + rawValue (原始 spread)."""
    spread = payload.get("spread", {}).get("weighted")
    if spread is not None:
        payload["score"] = percentile_score(
            "risk_appetite_daily", "spread_weighted", trade_date, spread,
        )
        payload["rawValue"] = spread


def calc_risk_appetite_cached(
    trade_date: date | str,
    *,
    window: int = DEFAULT_WINDOW,
    force: bool = False,
) -> dict:
    """cache-aside 版: 优先查 risk_appetite_daily, 没记录才现算 + 自动落盘.

    Args:
        trade_date: 目标日
        window: 窗口天数 (默认 20)
        force: True 跳过 cache 重算 + 覆盖 (维护用)
    """
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


# ---------------------------------------------------------------------------
# smoke
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json as _json
    print("=== calc_risk_appetite(2026-06-16) ===")
    print(_json.dumps(calc_risk_appetite("2026-06-16"), indent=2, ensure_ascii=False))