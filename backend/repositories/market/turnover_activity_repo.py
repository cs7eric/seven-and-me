"""成交活跃度 (Turnover Activity) 仓储.

公式:
  total_amount    = 当日全市场成交额 (亿元)
  avg_20d_amount  = 当日之前 20 个交易日的平均成交额 (亿元)
  ratio           = total_amount / avg_20d_amount

数据源: duckdb.market_overview_daily.total_amount (已校验成交额, 单位亿)
       不用 daily_raw.SUM(amount) 因为 TDX .day 文件 unit_scale 未归一化.

落盘: turnover_activity_daily (INSERT OR REPLACE by trade_date)
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Any

from backend.adapters.market.duckdb_store import get_conn
from backend.repositories.market.percentile_helper import (
    enrich_history_scores,
    percentile_score,
)
from backend.services.stock.trading_calendar import is_trading_day

logger = logging.getLogger(__name__)

DEFAULT_WINDOW = 20


def _to_date(v: date | str | None) -> date | None:
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(v)


# ---------------------------------------------------------------------------
# 1. 计算
# ---------------------------------------------------------------------------

def calc_turnover_activity(
    trade_date: date | str,
    *,
    window: int = DEFAULT_WINDOW,
) -> dict[str, Any] | None:
    """在 trade_date 算成交活跃度.

    从 market_overview_daily.total_amount 拉全市场成交额 (亿元),
    再算过去 window 日的平均成交额.

    Returns:
      {"tradeDate", "totalAmount", "avg20dAmount", "ratio", "sampleCount", "elapsedMs"}
      数据不足返 None.
    """
    td = _to_date(trade_date)
    if td is None:
        return None
    t0 = time.time()
    con = get_conn()

    # 拉 trade_date 及之前 N 天有 total_amount 的记录
    rows = con.execute(
        """
        SELECT trade_date, total_amount
          FROM market_overview_daily
         WHERE trade_date <= ? AND total_amount IS NOT NULL
         ORDER BY trade_date DESC
         LIMIT ?
        """,
        [td, window + 10],
    ).fetchall()

    if not rows:
        return None

    rows_asc = list(reversed(rows))  # ASC
    # 当前日 = rows_asc[-1]  (最新一日 = trade_date)
    today_row = rows_asc[-1]
    today_total = float(today_row[1])

    # 前 window 个交易日 (不含当天) 的均值
    prev = rows_asc[:-1]  # 去掉当天
    if not prev:
        return None
    sample = prev[-window:]  # 最多 window 个
    if not sample:
        return None
    avg_20d = sum(float(r[1]) for r in sample) / len(sample)
    ratio = today_total / avg_20d if avg_20d > 0 else 0.0

    elapsed_ms = int((time.time() - t0) * 1000)
    return {
        "tradeDate": td.isoformat(),
        "totalAmount": round(today_total, 2),
        "avg20dAmount": round(avg_20d, 2),
        "ratio": round(ratio, 4),
        "sampleCount": len(sample),
        "elapsedMs": elapsed_ms,
        "source": "duckdb.market_overview_daily",
    }


# ---------------------------------------------------------------------------
# 2. 落盘
# ---------------------------------------------------------------------------

def save_turnover_activity(payload: dict) -> None:
    """把 calc_turnover_activity 的 dict 落盘 (INSERT OR REPLACE by trade_date).

    同时把 score (历史分位) 一起落, 避免下游 composite 大卡重复现算.
    非交易日拒绝落盘 (历史上有 2026-02-24 春节调休 / 2026-06-13 端午调休脏数据).
    """
    td = _to_date(payload.get("tradeDate"))
    if td is None:
        raise ValueError("payload.tradeDate required")
    if not is_trading_day(td):
        logger.debug("save_turnover_activity skipped non-trading day: %s", td)
        return
    con = get_conn()
    con.execute("""
        INSERT OR REPLACE INTO turnover_activity_daily
            (trade_date, total_amount, avg_20d_amount, ratio, score,
             elapsed_ms, source, ingested_at)
        VALUES (?, ?, ?, ?, ?,
                ?, ?, current_timestamp)
    """, [
        td,
        float(payload.get("totalAmount") or 0),
        float(payload.get("avg20dAmount") or 0),
        float(payload.get("ratio") or 0),
        float(payload.get("score")) if payload.get("score") is not None else None,
        int(payload.get("elapsedMs") or 0),
        str(payload.get("source") or "duckdb.market_overview_daily"),
    ])


# ---------------------------------------------------------------------------
# 3. 读
# ---------------------------------------------------------------------------

_TA_COLS = (
    "trade_date", "total_amount", "avg_20d_amount", "ratio", "score",
    "elapsed_ms", "source",
)
_TA_SELECT = ", ".join(_TA_COLS)


def _row_to_payload(row: tuple) -> dict:
    return {
        "tradeDate": row[0].isoformat(),
        "totalAmount": float(row[1]) if row[1] is not None else None,
        "avg20dAmount": float(row[2]) if row[2] is not None else None,
        "ratio": float(row[3]) if row[3] is not None else None,
        "score": float(row[4]) if row[4] is not None else None,
        "elapsedMs": int(row[5]) if row[5] is not None else None,
        "source": str(row[6]),
        "fromCache": True,
    }


def get_turnover_activity(trade_date: date | str) -> dict | None:
    """按日期查 turnover_activity_daily. 无记录返 None (不抛)."""
    td = _to_date(trade_date)
    if td is None:
        return None
    con = get_conn()
    r = con.execute(
        f"SELECT {_TA_SELECT} FROM turnover_activity_daily WHERE trade_date = ?",
        [td],
    ).fetchone()
    return _row_to_payload(r) if r else None


def get_turnover_activity_history(
    start: date | str,
    end: date | str | None = None,
) -> list[dict]:
    """区间查 turnover_activity_daily (按 trade_date ASC)."""
    s = _to_date(start)
    e = _to_date(end) if end is not None else s
    if s is None or e is None:
        return []
    con = get_conn()
    rows = con.execute(
        f"SELECT {_TA_SELECT} FROM turnover_activity_daily "
        f"WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date ASC",
        [s, e],
    ).fetchall()
    items = [_row_to_payload(r) for r in rows]
    enrich_history_scores(items, "turnover_activity_daily", "ratio", e)
    return items


def coverage() -> dict[str, Any]:
    """运维用: 第一条 / 最后一条 / 总条数."""
    con = get_conn()
    r = con.execute(
        "SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM turnover_activity_daily"
    ).fetchone()
    return {
        "firstDate": r[0].isoformat() if r[0] else None,
        "lastDate": r[1].isoformat() if r[1] else None,
        "rowCount": int(r[2]) if r[2] else 0,
    }


# ---------------------------------------------------------------------------
# 4. cache-aside
# ---------------------------------------------------------------------------

def _add_score(payload: dict, trade_date: date | str) -> None:
    """给 payload 加 score (0-100 历史分位) + rawValue."""
    ratio = payload.get("ratio")
    if ratio is not None:
        payload["score"] = percentile_score(
            "turnover_activity_daily", "ratio", trade_date, ratio,
        )
        payload["rawValue"] = ratio


def calc_turnover_activity_cached(
    trade_date: date | str,
    *,
    window: int = DEFAULT_WINDOW,
    force: bool = False,
) -> dict | None:
    """cache-aside: 优先查表, 没记录才现算 + 自动落盘.

    Args:
        trade_date: 目标日
        window: 平均窗口 (默认 20)
        force: True 跳过 cache 重算 + 覆盖
    """
    if not force:
        cached = get_turnover_activity(trade_date)
        if cached is not None:
            # score 字段可能 NULL (旧数据没回填), 现补算
            if cached.get("score") is None:
                _add_score(cached, trade_date)
                # 把补算结果写回表 (不重算 ratio)
                try:
                    con = get_conn()
                    con.execute(
                        "UPDATE turnover_activity_daily SET score = ? WHERE trade_date = ?",
                        [float(cached["score"]), _to_date(trade_date)],
                    )
                except Exception:
                    logger.debug("backfill score for %s failed (non-fatal)", trade_date)
            else:
                _add_score_payload_only(cached)
            return cached
    payload = calc_turnover_activity(trade_date, window=window)
    if payload is None:
        return None
    # 先算 score, 再 save (save 包含 score)
    _add_score(payload, trade_date)
    try:
        save_turnover_activity(payload)
    except Exception:
        logger.debug("save_turnover_activity failed (non-fatal): %s", payload.get("tradeDate"))
    return payload


def _add_score_payload_only(payload: dict) -> None:
    """已有 score 时, 只补 rawValue 字段 (前端用)."""
    if payload.get("ratio") is not None and "rawValue" not in payload:
        payload["rawValue"] = payload["ratio"]


# ---------------------------------------------------------------------------
# smoke
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json as _json
    print("=== coverage ===")
    print(_json.dumps(coverage(), indent=2, ensure_ascii=False))
    print("\n=== calc_turnover_activity(2026-06-16) ===")
    r = calc_turnover_activity("2026-06-16")
    if r:
        print(_json.dumps(r, indent=2, ensure_ascii=False))
    print("\n=== calc_turnover_activity(2026-06-17) ===")
    r = calc_turnover_activity("2026-06-17")
    if r:
        print(_json.dumps(r, indent=2, ensure_ascii=False))
    print("\n=== get_turnover_activity_history(2026-06-01, 2026-06-17) ===")
    hist = get_turnover_activity_history("2026-06-01", "2026-06-17")
    print(_json.dumps(hist, indent=2, ensure_ascii=False))
