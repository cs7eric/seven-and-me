"""同花顺 90 行业主力资金 (industry 资金流 tab) duckdb 仓储.

数据源: 同花顺 data.10jqka.com.cn/funds/hyzjl/cate/3 (hexin-v JS 加密破解)
字段 (跟 ths_fund_flow_adapter 1:1):
  rank / industry / change_pct / inflow / outflow / net / company_count
  leader_stock / leader_change / leader_price

跟 market_pulse_sector_daily (§17) 字段高度相似但数据源不同, **并存不覆盖**:
  - §17 akshare.stock_fund_flow_industry (akshare 二次封装)
  - 本表 ths_fund_flow_adapter (直接 hexin-v 破解, 90 行业 + 完整字段)

写入路径 (3 处, 全部走 INSERT OR REPLACE 幂等):
  1. ths_fund_flow_service.refresh_industry_fund_flow() 末尾
  2. scripts/backfill_ths_industry_fund_flow.py (扫 history/*.json)
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
def upsert_fund_flow(
    rows: list[dict[str, Any]],
    trade_date: date | str | None = None,
    source: str = "ths.10jqka.com.cn",
) -> int:
    """批量写入 90 行业 当日资金流 (INSERT OR REPLACE by trade_date + industry).

    rows 元素含: industry / industry_code (optional) / rank / change_pct
                  / inflow / outflow / net / company_count
                  / leader_stock / leader_change / leader_price
    """
    if not rows:
        return 0
    td = _to_date(trade_date) or date.today()
    con = get_conn()
    sql = """
        INSERT OR REPLACE INTO ths_industry_fund_flow_daily
            (trade_date, industry, industry_code, rank, change_pct,
             inflow, outflow, net, company_count,
             leader_stock, leader_change, leader_price,
             source, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)
    """
    n = 0
    for r in rows:
        name = (r.get("industry") or "").strip()
        if not name:
            continue
        con.execute(sql, [
            td,
            name,
            str(r.get("industry_code") or "").strip() or None,
            int(r["rank"]) if r.get("rank") is not None else None,
            float(r.get("change_pct") or 0),
            float(r.get("inflow") or 0),
            float(r.get("outflow") or 0),
            float(r.get("net") or 0),
            int(r.get("company_count") or 0) if r.get("company_count") is not None else None,
            str(r.get("leader_stock") or "").strip() or None,
            float(r["leader_change"]) if r.get("leader_change") is not None else None,
            float(r["leader_price"]) if r.get("leader_price") is not None else None,
            source,
        ])
        n += 1
    return n


# ---------------------------------------------------------------------------
# 2. 读 API
# ---------------------------------------------------------------------------
_COLS = (
    "trade_date", "industry", "industry_code", "rank", "change_pct",
    "inflow", "outflow", "net", "company_count",
    "leader_stock", "leader_change", "leader_price", "source",
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
        "industry": str(row[1]),
        "industryCode": str(row[2]) if row[2] is not None else None,
        "rank": _i(3),
        "changePct": _f(4),
        "inflow": _f(5),
        "outflow": _f(6),
        "net": _f(7),
        "companyCount": _i(8),
        "leaderStock": str(row[9]) if row[9] is not None else None,
        "leaderChange": _f(10),
        "leaderPrice": _f(11),
        "source": str(row[12]) if row[12] is not None else None,
        "fromCache": True,
    }


def get_fund_flow_daily(trade_date: date | str) -> list[dict[str, Any]]:
    """单日 90 行业 (按 net DESC, 跟前端 IndustryFundFlowTable 默认排序一致)."""
    td = _to_date(trade_date)
    if td is None:
        return []
    con = get_conn()
    rows = con.execute(
        f"SELECT {_COL_SELECT} FROM ths_industry_fund_flow_daily "
        f"WHERE trade_date = ? ORDER BY net DESC",
        [td],
    ).fetchall()
    return [_row_to_payload(r) for r in rows]


def get_fund_flow_daily_topn(
    trade_date: date | str,
    top_n: int = 10,
) -> dict[str, Any]:
    """单日 Top N (净流入) + Bottom N (净流出)."""
    items = get_fund_flow_daily(trade_date)
    if not items:
        return {
            "tradeDate": _to_date(trade_date).isoformat() if _to_date(trade_date) else None,
            "topN": top_n,
            "top": [],
            "bottom": [],
            "count": 0,
        }
    return {
        "tradeDate": items[0]["tradeDate"],
        "topN": top_n,
        "top": items[:top_n],
        "bottom": list(reversed(items[-top_n:])) if len(items) >= top_n else list(reversed(items)),
        "count": len(items),
    }


def get_fund_flow_history(
    days: int = 10,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """近 N 个交易日快照 (按 trade_date DESC, 每日内按 net DESC).

    Args:
        days: 取最近 N 个交易日 (默认 10)
        top_n: 每只日只取前 N 个 (None = 全量 90)

    Returns:
      [{tradeDate, items: [...]}, ...]  按 tradeDate DESC
    """
    days = max(1, min(days, 120))
    con = get_conn()
    date_rows = con.execute(
        "SELECT DISTINCT trade_date FROM ths_industry_fund_flow_daily "
        "ORDER BY trade_date DESC LIMIT ?",
        [days],
    ).fetchall()
    if not date_rows:
        return []
    out: list[dict[str, Any]] = []
    for (td,) in date_rows:
        rows = con.execute(
            f"SELECT {_COL_SELECT} FROM ths_industry_fund_flow_daily "
            f"WHERE trade_date = ? ORDER BY net DESC "
            f"{f'LIMIT {int(top_n)}' if top_n else ''}",
            [td],
        ).fetchall()
        out.append({
            "tradeDate": td.isoformat(),
            "items": [_row_to_payload(r) for r in rows],
        })
    return out


def get_fund_flow_for_names(
    trade_date: date | str,
    names: list[str],
) -> list[dict[str, Any]]:
    """按行业名查当日快照 (跨日追踪 / 旋转趋势用)."""
    if not names:
        return []
    td = _to_date(trade_date)
    if td is None:
        return []
    con = get_conn()
    placeholders = ",".join(["?"] * len(names))
    rows = con.execute(
        f"SELECT {_COL_SELECT} FROM ths_industry_fund_flow_daily "
        f"WHERE trade_date = ? AND industry IN ({placeholders}) "
        f"ORDER BY net DESC",
        [td, *names],
    ).fetchall()
    return [_row_to_payload(r) for r in rows]


def get_fund_flow_for_industry(
    industry: str,
    days: int = 30,
    *,
    end: date | str | None = None,
) -> list[dict[str, Any]]:
    """单个行业近 N 个交易日的资金流序列 (跨日追踪, 按 trade_date ASC).

    Args:
        industry: 行业名 (中文, 跟 history 里的 key 一致)
        days: 取最近 N 个交易日 (默认 30, 上限 365)
        end: 截止日 (None = 最新一日)

    Returns:
      [{tradeDate, rank, changePct, inflow, outflow, net, companyCount,
        leaderStock, leaderChange, leaderPrice, ...}, ...]  按 trade_date ASC

    典型用法:
      - 半导体近 7 天: get_fund_flow_for_industry("半导体", 7)
      - 看行业从哪天开始有数据: 第一条 tradeDate 就是首个入库日
    """
    if not industry:
        return []
    days = max(1, min(days, 365))
    end_d = _to_date(end) if end is not None else None
    con = get_conn()
    if end_d is not None:
        rows = con.execute(
            f"SELECT {_COL_SELECT} FROM ths_industry_fund_flow_daily "
            f"WHERE industry = ? AND trade_date <= ? "
            f"ORDER BY trade_date DESC LIMIT ?",
            [industry, end_d, days],
        ).fetchall()
    else:
        rows = con.execute(
            f"SELECT {_COL_SELECT} FROM ths_industry_fund_flow_daily "
            f"WHERE industry = ? "
            f"ORDER BY trade_date DESC LIMIT ?",
            [industry, days],
        ).fetchall()
    return [_row_to_payload(r) for r in reversed(rows)]


def list_industries_with_data(days: int = 30) -> list[dict[str, Any]]:
    """列近 N 天有数据的所有行业 + 各自入库天数 (供前端"行业选择器"用)."""
    from datetime import date as _date, timedelta
    con = get_conn()
    cutoff = _date.today() - timedelta(days=days)
    rows = con.execute(
        """
        SELECT industry, industry_code, COUNT(*) AS days,
               MIN(trade_date) AS first_date, MAX(trade_date) AS last_date
          FROM ths_industry_fund_flow_daily
         WHERE trade_date >= ?
         GROUP BY industry, industry_code
         ORDER BY industry ASC
        """,
        [cutoff],
    ).fetchall()
    return [
        {
            "industry": str(r[0]),
            "industryCode": str(r[1]) if r[1] is not None else None,
            "days": int(r[2]) if r[2] else 0,
            "firstDate": r[3].isoformat() if r[3] else None,
            "lastDate": r[4].isoformat() if r[4] else None,
        }
        for r in rows
    ]


def coverage() -> dict[str, Any]:
    """覆盖度: first / last / 总行数 / 交易日数."""
    con = get_conn()
    r = con.execute(
        "SELECT MIN(trade_date), MAX(trade_date), COUNT(*), "
        "COUNT(DISTINCT trade_date) FROM ths_industry_fund_flow_daily"
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
    print("\n=== upsert smoke ===")
    n = upsert_fund_flow([{
        "industry": "半导体",
        "industry_code": "881268",
        "rank": 1,
        "change_pct": 2.35,
        "inflow": 25.5,
        "outflow": 12.3,
        "net": 13.2,
        "company_count": 142,
        "leader_stock": "中芯国际",
        "leader_change": 5.1,
        "leader_price": 85.3,
    }], trade_date="2026-06-16")
    print(f"upserted {n} row(s)")
    print("\n=== get_fund_flow_daily(2026-06-16) ===")
    print(_json.dumps(get_fund_flow_daily("2026-06-16"), indent=2, ensure_ascii=False))
