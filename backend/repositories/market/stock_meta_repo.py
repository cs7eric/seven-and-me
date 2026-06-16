"""股票元数据 + 板块/阈值分类.

数据来源 (按优先级):
  1. duckdb stock_universe 表 (code, name, market, sector, is_active, ipo/delisted)
  2. reference/stock-universe/_codes.json (code → name, exchange 兜底)
  3. 板块/阈值纯按 code 前缀推断 (无外部数据)

每个函数尽量短小独立, 单测 / 排查时能直接调用.
"""
from __future__ import annotations

import json
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.adapters.market.duckdb_store import get_conn
from backend.config.settings import STOCK_UNIVERSE_DIR  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 板块分类 (按 code 前缀)
# ---------------------------------------------------------------------------

def get_board_type(code: str) -> str:
    """板块分类: 'main_sh' | 'chinext' | 'star' | 'main_sz' | 'bse' | 'unknown'.

    main_sh   — 上交所主板 (60xxxx, 601xxx, 603xxx, 605xxx)
    chinext   — 深交所创业板 (300xxx, 301xxx)
    star      — 上交所科创板 (688xxx, 689xxx)
    main_sz   — 深交所主板/中小板 (000xxx, 001xxx, 002xxx, 003xxx)
    bse       — 北交所 (8xxxxx, 4xxxxx, 92xxxx)
    unknown   — 其他 (含可转债 / ETF / 指数 / B 股)
    """
    c = code.strip()
    if c.startswith(("600", "601", "603", "605")):
        return "main_sh"
    if c.startswith(("688", "689")):
        return "star"
    if c.startswith(("300", "301")):
        return "chinext"
    if c.startswith(("000", "001", "002", "003")):
        return "main_sz"
    if c.startswith(("8", "4")) or c.startswith("920"):
        return "bse"
    return "unknown"


def get_threshold(code: str, is_st: bool = False) -> float:
    """涨跌幅阈值 (返回小数, 0.10 表示 10%).

    主板 / 中小板 / ST(主板/中小板): ±10% (实际容差 9.95%)
    创业板 / 科创板: ±20% (实际 19.95%)
    北交所: ±30% (实际 29.95%)
    ST(创业板/科创板/北交所) 一律 ±5% (实际 4.95%)
    """
    if is_st:
        return 0.05
    board = get_board_type(code)
    if board in ("chinext", "star"):
        return 0.20
    if board == "bse":
        return 0.30
    return 0.10


# ---------------------------------------------------------------------------
# is_st 推断
# ---------------------------------------------------------------------------

def is_st_by_name(name: str | None) -> bool:
    """从股票名推断 ST 标记. 与 limit_emotion_service._is_st 一致."""
    if not name:
        return False
    upper = name.upper()
    return (upper.startswith("ST") or upper.startswith("*ST")
            or "退" in name)


# ---------------------------------------------------------------------------
# DuckDB universe 表 (优先)
# ---------------------------------------------------------------------------

def _universe_row_from_db(code: str) -> dict[str, Any] | None:
    """Query stock_universe table. Returns None on missing row OR missing table."""
    con = get_conn()
    try:
        r = con.execute("""
            SELECT code, name, market, sector, is_active, ipo_date, delist_date
              FROM stock_universe
             WHERE code = ?
        """, [code]).fetchone()
    except Exception:
        return None
    if not r:
        return None
    return {
        "code": r[0],
        "name": r[1],
        "market": r[2],
        "sector": r[3],
        "is_active": bool(r[4]),
        "ipo_date": r[5].isoformat() if r[5] else None,
        "delist_date": r[6].isoformat() if r[6] else None,
    }


# ---------------------------------------------------------------------------
# _codes.json 兜底 (cached)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _codes_json() -> dict[str, dict[str, Any]]:
    """Load reference/stock-universe/_codes.json → {code: {full_code, exchange, name}}.

    Actual file shape:
        {"version": 2, "trading_day": "...", "codes": [{code, full_code, exchange, name}, ...]}
    """
    p = Path(STOCK_UNIVERSE_DIR) / "_codes.json"
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    codes = data.get("codes") if isinstance(data, dict) else None
    if not isinstance(codes, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in codes:
        if isinstance(row, dict) and row.get("code"):
            out[row["code"]] = row
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_stock_meta(code: str) -> dict[str, Any] | None:
    """返回 {code, name, market, sector, is_active, is_st, exchange, board, ipo_date, delist_date}.

    优先 stock_universe 表; 兜底 _codes.json + 板块推断. 无任何记录返回 None.
    """
    code = code.strip()
    row = _universe_row_from_db(code)
    if row is None:
        # 兜底 _codes.json
        cj = _codes_json().get(code)
        if not cj:
            return None
        row = {
            "code": code,
            "name": cj.get("name") or "",
            "market": (cj.get("exchange") or "").lower() or None,
            "sector": None,
            "is_active": True,
            "ipo_date": None,
            "delist_date": None,
        }

    board = get_board_type(code)
    is_st = is_st_by_name(row.get("name"))
    return {
        **row,
        "is_st": is_st,
        "exchange": row.get("market"),  # alias for clarity
        "board": board,
        "threshold": get_threshold(code, is_st),
    }


def list_universe(active_only: bool = True) -> list[dict[str, Any]]:
    """所有股票 (或仅活跃) 的 [{code, name, market, is_active, board, is_st}, ...].

    数据源: stock_universe 表 (优) → _codes.json (兜底, 仅当表为空或不存在时).
    """
    con = get_conn()
    rows: list = []
    try:
        if active_only:
            rows = con.execute(
                "SELECT code, name, market, is_active FROM stock_universe "
                "WHERE is_active ORDER BY code"
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT code, name, market, is_active FROM stock_universe ORDER BY code"
            ).fetchall()
    except Exception:
        rows = []

    if rows:
        return [
            {
                "code": r[0],
                "name": r[1],
                "market": r[2],
                "is_active": bool(r[3]),
                "board": get_board_type(r[0]),
                "is_st": is_st_by_name(r[1]),
            }
            for r in rows
        ]

    # 兜底 _codes.json (stock_universe 为空时)
    cj = _codes_json()
    out = []
    for code, row in cj.items():
        out.append({
            "code": code,
            "name": row.get("name", ""),
            "market": row.get("exchange"),
            "is_active": True,
            "board": get_board_type(code),
            "is_st": is_st_by_name(row.get("name")),
        })
    return sorted(out, key=lambda x: x["code"])


def list_codes(active_only: bool = True) -> list[str]:
    """只返回 code 列表 (轻量)."""
    return [r["code"] for r in list_universe(active_only=active_only)]


# ---------------------------------------------------------------------------
# debug helpers
# ---------------------------------------------------------------------------

def coverage_summary() -> dict[str, Any]:
    """universe 概览: 总数, 板块分布, is_st 数."""
    items = list_universe(active_only=False)
    from collections import Counter
    boards = Counter(x["board"] for x in items)
    return {
        "total": len(items),
        "active": sum(1 for x in items if x["is_active"]),
        "by_board": dict(boards),
        "is_st_count": sum(1 for x in items if x["is_st"]),
    }


if __name__ == "__main__":
    import json as _json
    for code in ("000001", "600519", "300750", "688981", "920000", "ST华微", "002411"):
        m = get_stock_meta(code)
        if m:
            print(_json.dumps(m, ensure_ascii=False))
        else:
            print(f"{code}: <not found>")
    print()
    print("coverage_summary:", _json.dumps(coverage_summary(), ensure_ascii=False, indent=2))
