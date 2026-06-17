"""大盘概况 (大盘成交额 / 主力净流入 / 涨跌家数) duckdb 仓储.

数据源 (按字段分, 同一表不同字段可来自不同源):
  - 资金流 (main_net / super_large / large / medium / small + 各 ratio):
      akshare.stock_market_fund_flow (eastmoney 口径, 主力=超大+大)
  - 总成交额 / 涨跌家数 / 涨跌停家数 / 股票只数:
      akshare.stock_zh_a_spot_em (spot_em 口径) + eltdx TCP 兜底

写入路径:
  1. market_overview_akshare_service.capture_snapshot() 末尾
     → upsert_overview_akshare(payload) (写入资金流 + spot_em 字段)
  2. market_overview_eltdx_service.save_overview() 末尾
     → upsert_overview_eltdx(payload) (写入 eltdx 字段, 不覆盖已有)
  3. scripts/backfill_market_overview_daily.py
     → 扫 archive/*.json 历史回填

upsert 策略 (字段级):
  新值为 None 时, 保留旧值 (避免 akshare 失败时把已有的 eltdx 数据冲掉);
  新值非 None 时, 覆盖旧值. 走原生 SQL 的 COALESCE 实现.
"""
from __future__ import annotations

import json
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
# 1. 字段级 upsert (akshare 资金流 + spot_em)
# ---------------------------------------------------------------------------
# COALESCE 表达式: 新值 IS NULL 时用旧值, 否则用新值
_UPSERT_FIELDS = [
    # (column_name, payload_key, cast_type)
    # 大盘成交额 (akshare spot_em 优先; eltdx 兜底, 不覆盖已有)
    ("total_amount",            "totalAmount",          "DECIMAL(18, 4)"),
    ("total_volume",            "totalVolume",          "DECIMAL(18, 4)"),
    # 涨跌家数 (akshare spot_em 算的, 9.5% 宽松口径)
    ("rising_count",            "risingCount",          "INTEGER"),
    ("falling_count",           "fallingCount",         "INTEGER"),
    ("flat_count",              "flatCount",            "INTEGER"),
    ("limit_up_count",          "limitUpCount",         "INTEGER"),
    ("limit_down_count",        "limitDownCount",       "INTEGER"),
    ("stock_count",             "stockCount",           "INTEGER"),
    # 资金流 (akshare eastmoney)
    ("main_net_inflow",         "mainNetInflow",        "DECIMAL(18, 4)"),
    ("super_large_net_inflow",  "superLargeNetInflow",  "DECIMAL(18, 4)"),
    ("large_net_inflow",        "largeNetInflow",       "DECIMAL(18, 4)"),
    ("medium_net_inflow",       "mediumNetInflow",      "DECIMAL(18, 4)"),
    ("small_net_inflow",        "smallNetInflow",       "DECIMAL(18, 4)"),
    ("main_net_inflow_ratio",   "mainNetInflowRatio",   "DECIMAL(6, 2)"),
    ("super_large_net_ratio",   "superLargeNetInflowRatio", "DECIMAL(6, 2)"),
    ("large_net_ratio",         "largeNetInflowRatio",  "DECIMAL(6, 2)"),
    ("medium_net_ratio",        "mediumNetInflowRatio", "DECIMAL(6, 2)"),
    ("small_net_ratio",         "smallNetInflowRatio",  "DECIMAL(6, 2)"),
]


def upsert_overview_akshare(payload: dict[str, Any]) -> None:
    """把 akshare 资金流 + spot_em 数据 upsert 到 market_overview_daily.

    payload 由 market_overview_akshare_service.capture_snapshot() 提供,
    含 mainNetInflow / superLargeNetInflow / ... 字段 + totalAmount (spot_em 算) + 涨跌家数.

    字段级保护 (COALESCE): 已有值非 NULL 不被 None 覆盖.
    """
    td = _to_date(payload.get("tradingDate") or payload.get("trade_date"))
    if td is None:
        raise ValueError("payload.tradingDate required")

    con = get_conn()
    # 1) INSERT (如果不存在)
    con.execute(
        "INSERT OR IGNORE INTO market_overview_daily (trade_date, source) VALUES (?, ?)",
        [td, str(payload.get("source") or "akshare")],
    )
    # 2) 字段级 UPDATE: 新值非 NULL 时, COALESCE 保护 (已有值优先)
    set_clauses = []
    params: list[Any] = []
    for col, key, cast in _UPSERT_FIELDS:
        v = payload.get(key)
        if v is None:
            continue
        # 浮点字段走 cast
        if cast.startswith("DECIMAL"):
            set_clauses.append(f"{col} = COALESCE({col}, CAST(? AS {cast}))")
            params.append(float(v))
        elif cast == "INTEGER":
            set_clauses.append(f"{col} = COALESCE({col}, CAST(? AS INTEGER))")
            params.append(int(v))
    if set_clauses:
        # 末尾追加 source 标记 (合并去重: akshare 写过后, eltdx 写也保留 akshare 标记)
        existing_src = con.execute(
            "SELECT source FROM market_overview_daily WHERE trade_date = ?", [td]
        ).fetchone()
        existing_src_str = (existing_src[0] or "") if existing_src else ""
        new_src = str(payload.get("source") or "akshare")
        if existing_src_str and existing_src_str != new_src:
            merged = f"{existing_src_str}+{new_src}" if "+" not in existing_src_str else existing_src_str
        else:
            merged = new_src
        set_clauses.append("source = ?")
        params.append(merged[:32])
        params.append(td)
        sql = f"UPDATE market_overview_daily SET {', '.join(set_clauses)} WHERE trade_date = ?"
        con.execute(sql, params)


def upsert_overview_eltdx(payload: dict[str, Any]) -> None:
    """把 eltdx 数据 upsert 到 market_overview_daily.

    eltdx 提供的字段: totalAmount / risingCount / fallingCount / flatCount /
    limitUpCount / limitDownCount / stockCount.

    字段级保护 (COALESCE): akshare 已有值不覆盖.
    """
    td = _to_date(payload.get("tradingDate") or payload.get("trade_date"))
    if td is None:
        return

    eltdx_fields = {
        "totalAmount":     "total_amount",
        "risingCount":     "rising_count",
        "fallingCount":    "falling_count",
        "flatCount":       "flat_count",
        "limitUpCount":    "limit_up_count",
        "limitDownCount":  "limit_down_count",
        "stockCount":      "stock_count",
    }
    values = {col: payload.get(key) for key, col in eltdx_fields.items() if payload.get(key) is not None}
    if not values:
        return

    con = get_conn()
    con.execute(
        "INSERT OR IGNORE INTO market_overview_daily (trade_date, source) VALUES (?, ?)",
        [td, "eltdx"],
    )

    set_clauses: list[str] = []
    params: list[Any] = []
    for col, v in values.items():
        # 字段级 COALESCE 保护: 新值不为 NULL 时才覆盖, 已有值保留
        if isinstance(v, float):
            set_clauses.append(f"{col} = COALESCE({col}, CAST(? AS DECIMAL(18, 4)))")
            params.append(v)
        elif isinstance(v, int):
            set_clauses.append(f"{col} = COALESCE({col}, CAST(? AS INTEGER))")
            params.append(v)
    if set_clauses:
        existing_src = con.execute(
            "SELECT source FROM market_overview_daily WHERE trade_date = ?", [td]
        ).fetchone()
        existing_src_str = (existing_src[0] or "") if existing_src else ""
        new_src = "eltdx"
        if existing_src_str and existing_src_str != new_src:
            merged = f"{existing_src_str}+{new_src}" if "+" not in existing_src_str else existing_src_str
        else:
            merged = new_src
        set_clauses.append("source = ?")
        params.append(merged[:32])
        params.append(td)
        sql = f"UPDATE market_overview_daily SET {', '.join(set_clauses)} WHERE trade_date = ?"
        con.execute(sql, params)


# ---------------------------------------------------------------------------
# 2. 读 API (历史序列 / 单日)
# ---------------------------------------------------------------------------
_COLS = (
    "trade_date", "total_amount", "total_volume",
    "rising_count", "falling_count", "flat_count",
    "limit_up_count", "limit_down_count", "stock_count",
    "main_net_inflow", "super_large_net_inflow", "large_net_inflow",
    "medium_net_inflow", "small_net_inflow",
    "main_net_inflow_ratio", "super_large_net_ratio", "large_net_ratio",
    "medium_net_ratio", "small_net_ratio",
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
        "totalAmount": _f(1),
        "totalVolume": _f(2),
        "risingCount": _i(3),
        "fallingCount": _i(4),
        "flatCount": _i(5),
        "limitUpCount": _i(6),
        "limitDownCount": _i(7),
        "stockCount": _i(8),
        "mainNetInflow": _f(9),
        "superLargeNetInflow": _f(10),
        "largeNetInflow": _f(11),
        "mediumNetInflow": _f(12),
        "smallNetInflow": _f(13),
        "mainNetInflowRatio": _f(14),
        "superLargeNetInflowRatio": _f(15),
        "largeNetInflowRatio": _f(16),
        "mediumNetInflowRatio": _f(17),
        "smallNetInflowRatio": _f(18),
        "source": str(row[19]) if row[19] is not None else None,
        "fromCache": True,
    }


def get_overview(trade_date: date | str) -> dict | None:
    """按日期查 market_overview_daily. 无记录返 None (不抛)."""
    td = _to_date(trade_date)
    if td is None:
        return None
    con = get_conn()
    r = con.execute(
        f"SELECT {_COL_SELECT} FROM market_overview_daily WHERE trade_date = ?",
        [td],
    ).fetchone()
    return _row_to_payload(r) if r else None


def get_overview_history(
    start: date | str,
    end: date | str | None = None,
    limit: int = 60,
) -> list[dict[str, Any]]:
    """区间查 market_overview_daily (按 trade_date DESC LIMIT, 再升序返回).

    Args:
        start: 起始日
        end: 结束日 (None = start 当天)
        limit: 最大返回条数 (默认 60)
    """
    s = _to_date(start)
    e = _to_date(end) if end is not None else s
    if s is None or e is None:
        return []
    limit = max(1, min(limit, 500))
    con = get_conn()
    rows = con.execute(
        f"SELECT {_COL_SELECT} FROM market_overview_daily "
        f"WHERE trade_date BETWEEN ? AND ? "
        f"ORDER BY trade_date DESC LIMIT ?",
        [s, e, limit],
    ).fetchall()
    return [_row_to_payload(r) for r in reversed(rows)]


def coverage() -> dict[str, Any]:
    """覆盖度: first / last / count, 运维用."""
    con = get_conn()
    r = con.execute(
        "SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM market_overview_daily"
    ).fetchone()
    return {
        "firstDate": r[0].isoformat() if r[0] else None,
        "lastDate": r[1].isoformat() if r[1] else None,
        "rowCount": int(r[2]) if r[2] else 0,
    }


# ---------------------------------------------------------------------------
# smoke
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json as _json
    print("=== coverage ===")
    print(_json.dumps(coverage(), indent=2, ensure_ascii=False))
    print("\n=== get_overview_history(2026-06-01, 2026-06-16, limit=5) ===")
    print(_json.dumps(get_overview_history("2026-06-01", "2026-06-16", limit=5), indent=2, ensure_ascii=False))
