"""股票元数据 + 板块/阈值分类 — PostgreSQL sec_stock_universe first."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import text

from backend.config.database import session_scope
from backend.config.settings import STOCK_UNIVERSE_DIR  # type: ignore[attr-defined]


def get_board_type(code: str) -> str:
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
    if is_st:
        return 0.05
    board = get_board_type(code)
    if board in ("chinext", "star"):
        return 0.20
    if board == "bse":
        return 0.30
    return 0.10


def is_st_by_name(name: str | None) -> bool:
    if not name:
        return False
    upper = name.upper()
    return upper.startswith("ST") or upper.startswith("*ST") or "退" in name


def _universe_row_from_pg(code: str) -> dict[str, Any] | None:
    try:
        with session_scope() as db:
            row = db.execute(
                text("""
                    SELECT code, name, market, sector, is_active, ipo_date, delist_date
                      FROM cynexus_appl_market.sec_stock_universe
                     WHERE code = :code AND deleted_at IS NULL
                     LIMIT 1
                """),
                {"code": code},
            ).mappings().first()
    except Exception:
        return None
    if not row:
        return None
    return {
        "code": row["code"],
        "name": row["name"],
        "market": row["market"],
        "sector": row["sector"],
        "is_active": bool(row["is_active"]),
        "ipo_date": row["ipo_date"].isoformat() if row["ipo_date"] else None,
        "delist_date": row["delist_date"].isoformat() if row["delist_date"] else None,
    }


@lru_cache(maxsize=1)
def _codes_json() -> dict[str, dict[str, Any]]:
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
            out[str(row["code"])] = row
    return out


def get_stock_meta(code: str) -> dict[str, Any] | None:
    code = code.strip()
    row = _universe_row_from_pg(code)
    if row is None:
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
        "exchange": row.get("market"),
        "board": board,
        "threshold": get_threshold(code, is_st),
    }


def list_universe(active_only: bool = True) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        where_active = "AND is_active IS TRUE" if active_only else ""
        with session_scope() as db:
            rows = [dict(r) for r in db.execute(
                text(f"""
                    SELECT code, name, market, is_active
                      FROM cynexus_appl_market.sec_stock_universe
                     WHERE deleted_at IS NULL {where_active}
                     ORDER BY code
                """)
            ).mappings().all()]
    except Exception:
        rows = []

    if rows:
        return [
            {
                "code": r["code"],
                "name": r["name"],
                "market": r["market"],
                "is_active": bool(r["is_active"]),
                "board": get_board_type(r["code"]),
                "is_st": is_st_by_name(r["name"]),
            }
            for r in rows
        ]

    out = []
    for code, row in _codes_json().items():
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
    return [r["code"] for r in list_universe(active_only=active_only)]


def coverage_summary() -> dict[str, Any]:
    items = list_universe(active_only=False)
    from collections import Counter
    boards = Counter(x["board"] for x in items)
    return {
        "total": len(items),
        "active": sum(1 for x in items if x["is_active"]),
        "by_board": dict(boards),
        "is_st_count": sum(1 for x in items if x["is_st"]),
    }
