"""市场脉搏 · 90 行业 (akshare stock_fund_flow_industry) duckdb 仓储.

字段含义:
  - sector_name: 行业名 ("半导体" / "银行" / ...)
  - sector_index: 行业指数代码 (e.g. "880491")
  - change_pct: 行业涨跌幅 (%)
  - inflow / outflow / main_net: 行业 流入 / 流出 / 净额, 单位亿
  - stock_count: 行业公司家数
  - leading_stock / leading_change_pct / leading_price: 领涨股信息

写入路径 (3 处, 全部走 INSERT OR REPLACE 幂等):
  1. market_pulse_service.build_capital_flow() 末尾
     (盘内每 10min + 收盘 15:30 触发, 当日 90 行)
  2. market_pulse_service.snapshot_today_rotation() 末尾
     (收盘 15:30 落 rotation JSON 时, 顺便 upsert 90 行 — 实际上是同 90 行)
  3. scripts/backfill_market_overview_daily.py
     (扫 rotation/YYYY-MM-DD.json 历史回填)
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from backend.adapters.market.duckdb_store import get_conn

logger = logging.getLogger(__name__)


def _to_date(v: date | str | None) -> date | None:
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(v)


# ---------------------------------------------------------------------------
# 1. 批量 upsert (90 行业, 给 service + backfill 脚本用)
# ---------------------------------------------------------------------------
def upsert_sector_spot(
    rows: list[dict[str, Any]],
    trade_date: date | str | None = None,
    source: str = "akshare.stock_fund_flow_industry",
) -> int:
    """批量写入 90 行业当日快照 (INSERT OR REPLACE by trade_date + sector_name).

    rows 元素含: name / index / changePct / inflow / outflow / mainNet / stockCount
                  / leadingStock / leadingChangePct / leadingPrice

    Args:
        rows: 行业列表 (90 行)
        trade_date: 交易日; None 时用今天 (北京时间)
        source: 来源标签

    Returns:
        写入行数 (重复 trade_date+sector_name 走 REPLACE 覆盖)
    """
    if not rows:
        return 0
    td = _to_date(trade_date) or date.today()
    con = get_conn()
    sql = """
        INSERT OR REPLACE INTO market_pulse_sector_daily
            (trade_date, sector_name, sector_index, change_pct,
             inflow, outflow, main_net, stock_count,
             leading_stock, leading_change_pct, leading_price,
             source, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)
    """
    n = 0
    for r in rows:
        name = (r.get("name") or "").strip()
        if not name:
            continue
        con.execute(sql, [
            td,
            name,
            str(r.get("index") or "") or None,
            float(r.get("changePct") or 0),
            float(r.get("inflow") or 0),
            float(r.get("outflow") or 0),
            float(r.get("mainNet") or 0),
            int(r.get("stockCount") or 0) if r.get("stockCount") is not None else None,
            str(r.get("leadingStock") or "").strip() or None,
            float(r.get("leadingChangePct")) if r.get("leadingChangePct") is not None else None,
            float(r.get("leadingPrice")) if r.get("leadingPrice") is not None else None,
            source,
        ])
        n += 1
    return n


# ---------------------------------------------------------------------------
# 2. 读 API (单日 + 历史 + Top N)
# ---------------------------------------------------------------------------
_COLS = (
    "trade_date", "sector_name", "sector_index", "change_pct",
    "inflow", "outflow", "main_net", "stock_count",
    "leading_stock", "leading_change_pct", "leading_price",
    "source",
)
_COL_SELECT = ", ".join(_COLS)


def _row_to_payload(row: tuple) -> dict[str, Any]:
    def _f(i: int) -> float | None:
        v = row[i]
        return float(v) if v is not None else None

    def _i(i: int) -> int | None:
        v = row[i]
        return int(v) if v is not None else None

    return {
        "tradeDate": row[0].isoformat(),
        "name": str(row[1]),
        "index": str(row[2]) if row[2] is not None else None,
        "changePct": _f(3),
        "inflow": _f(4),
        "outflow": _f(5),
        "mainNet": _f(6),
        "stockCount": _i(7),
        "leadingStock": str(row[8]) if row[8] is not None else None,
        "leadingChangePct": _f(9),
        "leadingPrice": _f(10),
        "source": str(row[11]) if row[11] is not None else None,
        "fromCache": True,
    }


def get_sector_daily(trade_date: date | str) -> list[dict[str, Any]]:
    """单日 90 行业快照 (按 change_pct DESC, 取全部)."""
    td = _to_date(trade_date)
    if td is None:
        return []
    con = get_conn()
    rows = con.execute(
        f"SELECT {_COL_SELECT} FROM market_pulse_sector_daily "
        f"WHERE trade_date = ? ORDER BY change_pct DESC",
        [td],
    ).fetchall()
    return [_row_to_payload(r) for r in rows]


def get_sector_daily_topn(
    trade_date: date | str,
    top_n: int = 10,
) -> dict[str, Any]:
    """单日 Top N + Bottom N 行业 (供 market-pulse 页面用).

    Returns:
      {
        tradeDate, topN,
        top:    [...],   # 涨幅榜
        bottom: [...],   # 跌幅榜
        count:  N        # 该日入库的行业总数 (正常 90)
      }
    """
    sectors = get_sector_daily(trade_date)
    if not sectors:
        return {
            "tradeDate": _to_date(trade_date).isoformat() if _to_date(trade_date) else None,
            "topN": top_n,
            "top": [],
            "bottom": [],
            "count": 0,
        }
    return {
        "tradeDate": _to_date(trade_date).isoformat() if _to_date(trade_date) else sectors[0].get("tradeDate"),
        "topN": top_n,
        "top": sectors[:top_n],
        "bottom": list(reversed(sectors[-top_n:])) if len(sectors) >= top_n else list(reversed(sectors)),
        "count": len(sectors),
    }


def get_sector_history(
    days: int = 10,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """近 N 个交易日的行业快照 (按 trade_date DESC, 每日内按 change_pct DESC).

    Args:
        days: 取最近 N 个交易日 (默认 10)
        top_n: 每只日只取前 N 个 (None = 全量 90)

    Returns:
      [{tradeDate, items: [...]}, ...]  按 tradeDate DESC
    """
    days = max(1, min(days, 120))
    con = get_conn()
    # 拿最近 N 个交易日 (distinct trade_date)
    date_rows = con.execute(
        "SELECT DISTINCT trade_date FROM market_pulse_sector_daily "
        "ORDER BY trade_date DESC LIMIT ?",
        [days],
    ).fetchall()
    if not date_rows:
        return []
    out: list[dict[str, Any]] = []
    for (td,) in date_rows:
        rows = con.execute(
            f"SELECT {_COL_SELECT} FROM market_pulse_sector_daily "
            f"WHERE trade_date = ? ORDER BY change_pct DESC "
            f"{f'LIMIT {int(top_n)}' if top_n else ''}",
            [td],
        ).fetchall()
        out.append({
            "tradeDate": td.isoformat(),
            "items": [_row_to_payload(r) for r in rows],
        })
    return out


def get_sector_for_names(
    trade_date: date | str,
    names: list[str],
) -> list[dict[str, Any]]:
    """按行业名查当日快照 (旋转趋势 / 跨日追踪用)."""
    if not names:
        return []
    td = _to_date(trade_date)
    if td is None:
        return []
    con = get_conn()
    placeholders = ",".join(["?"] * len(names))
    rows = con.execute(
        f"SELECT {_COL_SELECT} FROM market_pulse_sector_daily "
        f"WHERE trade_date = ? AND sector_name IN ({placeholders}) "
        f"ORDER BY change_pct DESC",
        [td, *names],
    ).fetchall()
    return [_row_to_payload(r) for r in rows]


def coverage() -> dict[str, Any]:
    """覆盖度: first / last / 总行数 / 交易日数."""
    con = get_conn()
    r = con.execute(
        "SELECT MIN(trade_date), MAX(trade_date), COUNT(*), "
        "COUNT(DISTINCT trade_date) FROM market_pulse_sector_daily"
    ).fetchone()
    return {
        "firstDate": r[0].isoformat() if r[0] else None,
        "lastDate": r[1].isoformat() if r[1] else None,
        "rowCount": int(r[2]) if r[2] else 0,
        "tradeDayCount": int(r[3]) if r[3] else 0,
    }


# ---------------------------------------------------------------------------
# smoke
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json as _json
    print("=== coverage ===")
    print(_json.dumps(coverage(), indent=2, ensure_ascii=False))
    print("\n=== upsert_sector_spot (单条 smoke) ===")
    n = upsert_sector_spot([{
        "name": "半导体",
        "index": "880491",
        "changePct": 2.35,
        "inflow": 12.5,
        "outflow": 8.2,
        "mainNet": 4.3,
        "stockCount": 142,
        "leadingStock": "中芯国际",
        "leadingChangePct": 5.1,
        "leadingPrice": 85.3,
    }], trade_date="2026-06-16")
    print(f"upserted {n} row(s)")
    print("\n=== get_sector_daily_topn(2026-06-16) ===")
    print(_json.dumps(get_sector_daily_topn("2026-06-16", top_n=5), indent=2, ensure_ascii=False))
