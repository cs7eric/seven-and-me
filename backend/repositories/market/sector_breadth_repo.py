"""板块扩散 (Market Pulse · Sector Breadth) duckdb 仓储.

公式 (跟 schema.sql §19 一致):
  advancing = count(industry where change_pct > 0)
  declining = count(industry where change_pct < 0)
  flat      = count(industry where change_pct = 0)
  total     = count(*)  (90 行业全量, 当前 91 含重复)
  advance_pct = advancing / total

数据源: ths_industry_fund_flow_daily (§18) — 同花顺 hexin-v 90 行业
计算: SQL 一次扫, 单日 1 行, 在 ths_industry_fund_flow_daily 数据齐后跑.

写入路径 (2 处, INSERT OR REPLACE 幂等):
  1. ths_industry_fund_flow_daily_scheduler._job_run_backfill() 末尾
     (工作日 17:15 同 ths 一起, 不需要额外 cron)
  2. scripts/backfill_sector_breadth.py (一次性回填所有历史日)

用途: market-pulse 页面 "板块扩散" card / 跨日 advance_pct 趋势.
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

from backend.adapters.market.duckdb_store import get_conn

logger = logging.getLogger(__name__)


def _to_date(v: date | str | None) -> date | None:
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(v)


# ---------------------------------------------------------------------------
# 1. 核心: 1 日 1 行, SQL 聚合自 ths_industry_fund_flow_daily
# ---------------------------------------------------------------------------
def upsert_sector_breadth(trade_date: date | str) -> int:
    """计算指定交易日的板块扩散并 upsert.

    Returns:
        写入行数 (0 表示该日 ths_industry_fund_flow_daily 无数据, 跳过)
    """
    td = _to_date(trade_date)
    if td is None:
        return 0
    con = get_conn()
    t0 = time.time()

    # 单次 SQL: 一次扫 ths_industry_fund_flow_daily, 算 4 个 count
    row = con.execute(
        """
        SELECT
            SUM(CASE WHEN change_pct >  0 THEN 1 ELSE 0 END) AS advancing,
            SUM(CASE WHEN change_pct <  0 THEN 1 ELSE 0 END) AS declining,
            SUM(CASE WHEN change_pct =  0 THEN 1 ELSE 0 END) AS flat,
            COUNT(*) AS total
          FROM ths_industry_fund_flow_daily
         WHERE trade_date = ?
        """,
        [td],
    ).fetchone()
    if not row or row[3] is None or int(row[3]) == 0:
        # 该日 ths_industry_fund_flow_daily 没数据, 跳过 (允许 sector_breadth 滞后 1 天)
        return 0

    advancing, declining, flat, total = int(row[0] or 0), int(row[1] or 0), int(row[2] or 0), int(row[3])
    # advance_pct: 0-1, 4 位小数 (前端显示 *100 转 %)
    advance_pct = round(advancing / total, 4) if total > 0 else 0.0
    elapsed_ms = int((time.time() - t0) * 1000)

    con.execute(
        """
        INSERT OR REPLACE INTO market_pulse_sector_breadth_daily
            (trade_date, advancing, declining, flat, total,
             advance_pct, source, elapsed_ms, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)
        """,
        [td, advancing, declining, flat, total,
         advance_pct, "ths_industry_fund_flow_daily", elapsed_ms],
    )
    return 1


# ---------------------------------------------------------------------------
# 2. 读 API
# ---------------------------------------------------------------------------
_COLS = (
    "trade_date", "advancing", "declining", "flat", "total",
    "advance_pct", "source", "elapsed_ms",
)
_COL_SELECT = ", ".join(_COLS)


def _row_to_payload(row: tuple) -> dict[str, Any]:
    advance_pct = float(row[5]) if row[5] is not None else 0.0
    return {
        "tradeDate": row[0].isoformat(),
        "advancing": int(row[1]) if row[1] is not None else 0,
        "declining": int(row[2]) if row[2] is not None else 0,
        "flat": int(row[3]) if row[3] is not None else 0,
        "total": int(row[4]) if row[4] is not None else 0,
        "advancePct": advance_pct,
        # score: 板块扩散天然百分比 → ×100 直接得 0-100 情绪得分
        # (上涨行业占比 0~1, 跟 ma_count 上涨占比同口径, 不需要百分位)
        "score": round(advance_pct * 100, 2),
        "source": str(row[6]) if row[6] is not None else None,
        "elapsedMs": int(row[7]) if row[7] is not None else None,
        "fromCache": True,
    }


def get_sector_breadth(trade_date: date | str) -> dict | None:
    """按日期查 market_pulse_sector_breadth_daily. 无记录返 None (不抛)."""
    td = _to_date(trade_date)
    if td is None:
        return None
    con = get_conn()
    r = con.execute(
        f"SELECT {_COL_SELECT} FROM market_pulse_sector_breadth_daily "
        f"WHERE trade_date = ?",
        [td],
    ).fetchone()
    return _row_to_payload(r) if r else None


def get_sector_breadth_history(
    start: date | str,
    end: date | str | None = None,
    limit: int = 60,
) -> list[dict[str, Any]]:
    """区间查 (按 trade_date ASC). 跨日趋势图用."""
    s = _to_date(start)
    e = _to_date(end) if end is not None else s
    if s is None or e is None:
        return []
    limit = max(1, min(limit, 365))
    con = get_conn()
    rows = con.execute(
        f"SELECT {_COL_SELECT} FROM market_pulse_sector_breadth_daily "
        f"WHERE trade_date BETWEEN ? AND ? "
        f"ORDER BY trade_date DESC LIMIT ?",
        [s, e, limit],
    ).fetchall()
    return [_row_to_payload(r) for r in reversed(rows)]


def coverage() -> dict[str, Any]:
    """覆盖度: first / last / 总行数."""
    con = get_conn()
    r = con.execute(
        "SELECT MIN(trade_date), MAX(trade_date), COUNT(*) "
        "FROM market_pulse_sector_breadth_daily"
    ).fetchone()
    return {
        "firstDate": r[0].isoformat() if r[0] else None,
        "lastDate": r[1].isoformat() if r[1] else None,
        "rowCount": int(r[2]) if r[2] else 0,
    }


def calc_sector_breadth_cached(
    trade_date: date | str,
    *,
    force: bool = False,
) -> dict | None:
    """cache-aside 版: 优先查 market_pulse_sector_breadth_daily, 没记录才现算 + 自动落盘.

    Returns: {ok, tradeDate, advancing, declining, flat, total, advancePct, source, ...}
             返回 None 表示 ths_industry_fund_flow_daily 也没数据 (不是交易日)
    """
    if not force:
        cached = get_sector_breadth(trade_date)
        if cached is not None:
            return {"ok": True, **cached}
    # 现算 + 自动落盘
    n = upsert_sector_breadth(trade_date)
    if n == 0:
        return None
    payload = get_sector_breadth(trade_date)
    return {"ok": True, **(payload or {})}


# ---------------------------------------------------------------------------
# smoke
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json as _json
    print("=== coverage ===")
    print(_json.dumps(coverage(), indent=2, ensure_ascii=False))
    print("\n=== upsert smoke ===")
    n = upsert_sector_breadth("2026-06-16")
    print(f"upserted {n} row(s)")
    print("\n=== get_sector_breadth(2026-06-16) ===")
    print(_json.dumps(get_sector_breadth("2026-06-16"), indent=2, ensure_ascii=False))
