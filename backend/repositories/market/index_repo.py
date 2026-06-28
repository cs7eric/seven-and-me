"""宽基指数 K 线查询 (中证1000 / 沪深300) — ClickHouse + PostgreSQL."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import text

from backend.adapters.market.clickhouse_store import command, insert, query_one, query_rows
from backend.config.database import session_scope
from backend.repositories.market.market_pg_cynexus_repo import coverage as _pg_coverage, execute_upsert, to_date
from backend.services.stock.trading_calendar import is_trading_day

import logging
logger = logging.getLogger(__name__)

INDEX_TARGETS: list[dict[str, str]] = [
    {"name": "上证指数", "code": "000001", "full": "sh000001", "exchange": "sh"},
    {"name": "沪深300", "code": "000300", "full": "sh000300", "exchange": "sh"},
    {"name": "中证1000", "code": "000852", "full": "sh000852", "exchange": "sh"},
]


def _to_date(v: date | str | None) -> date | None:
    return to_date(v)


def _short_code(full_code: str | None) -> str:
    if not full_code:
        return ""
    return str(full_code).removeprefix("sh").removeprefix("sz")


def upsert_index_daily(code: str, rows: list[dict[str, Any]], source: str = "eastmoney") -> int:
    """批量写入指数日 K 到 ClickHouse index_daily_raw.

    ClickHouse 表是 MergeTree, 没有唯一键语义；这里先按日期删除再插入，避免常规重跑
    产生重复行。删除 mutation 使用同步等待。
    """
    cleaned: list[tuple[Any, ...]] = []
    for r in rows:
        td = _to_date(r.get("trade_date") or r.get("date"))
        if td is None or not is_trading_day(td):
            continue
        cleaned.append((
            code, td,
            float(r.get("open") or 0),
            float(r.get("high") or 0),
            float(r.get("low") or 0),
            float(r.get("close") or 0),
            int(r.get("volume") or 0),
            float(r.get("amount") or 0),
            source,
            datetime.now(),
        ))
    if not cleaned:
        return 0
    dates = sorted({row[1].isoformat() for row in cleaned})
    date_list = ", ".join(f"toDate('{d}')" for d in dates)
    command(
        f"ALTER TABLE index_daily_raw DELETE WHERE code = %(code)s AND trade_date IN ({date_list})",
        {"code": code},
        settings={"mutations_sync": 1},
    )
    insert(
        "index_daily_raw",
        cleaned,
        ["code", "trade_date", "open", "high", "low", "close", "volume", "amount", "source", "ingested_at"],
    )
    return len(cleaned)


def get_index_daily(code: str, days: int = 30) -> list[dict[str, Any]]:
    if not code:
        return []
    days = max(1, min(days, 1500))
    rows = query_rows(
        """
        SELECT code, trade_date, anyLast(open), anyLast(high), anyLast(low), anyLast(close),
               anyLast(volume), anyLast(amount)
          FROM index_daily_raw
         WHERE code = %s
         GROUP BY code, trade_date
         ORDER BY trade_date DESC
         LIMIT %s
        """,
        (code, days),
    )
    out: list[dict[str, Any]] = []
    for r in reversed(rows):
        out.append({
            "code": r[0],
            "trade_date": r[1].isoformat(),
            "open": float(r[2]),
            "high": float(r[3]),
            "low": float(r[4]),
            "close": float(r[5]),
            "volume": int(r[6]),
            "amount": float(r[7]),
        })
    return out


def _bars_up_to(code: str, as_of_date, n: int) -> list[tuple]:
    rows = query_rows(
        """
        SELECT trade_date, anyLast(close) AS close
          FROM index_daily_raw
         WHERE code = %s AND trade_date <= %s
         GROUP BY trade_date
         ORDER BY trade_date DESC
         LIMIT %s
        """,
        (code, as_of_date, n),
    )
    return list(reversed(rows))


def latest_index_trade_date(code: str = "sh000001", as_of_date: date | str | None = None) -> date | None:
    """Return the latest ClickHouse index_daily_raw trade date for code."""
    params: list[Any] = [code]
    where = "code = %s"
    if as_of_date is not None:
        td = _to_date(as_of_date)
        if td is None:
            return None
        where += " AND trade_date <= %s"
        params.append(td)
    row = query_one(f"SELECT MAX(trade_date) FROM index_daily_raw WHERE {where}", tuple(params))
    if not row or row[0] is None:
        return None
    v = row[0]
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


def has_index_kline(code: str, trade_date: date | str) -> bool:
    """Return whether ClickHouse has an index_daily_raw row for code/date."""
    td = _to_date(trade_date)
    if td is None:
        return False
    row = query_one(
        "SELECT count() > 0 FROM index_daily_raw WHERE code = %s AND trade_date = %s",
        (code, td),
    )
    return bool(row[0]) if row else False


def get_index_returns(days: int = 5) -> list[dict[str, Any]]:
    days = max(1, min(days, 60))
    rows_needed = days + 1
    out: list[dict[str, Any]] = []
    for tgt in INDEX_TARGETS:
        full = tgt["full"]
        bars = query_rows(
            """
            SELECT trade_date, anyLast(close) AS close
              FROM index_daily_raw
             WHERE code = %s
             GROUP BY trade_date
             ORDER BY trade_date DESC
             LIMIT %s
            """,
            (full, rows_needed),
        )
        bars = list(reversed(bars))
        if not bars:
            out.append({
                "name": tgt["name"], "code": tgt["code"], "fullCode": full,
                "current": None, "currentDate": None, "baseClose": None,
                "baseDate": None, "returnPct": None, "daily": [], "available": False,
            })
            continue
        recent = bars[-days:] if len(bars) >= days else bars
        daily: list[dict[str, Any]] = []
        for i, (td, close) in enumerate(recent):
            if i == 0:
                daily_return = None
            else:
                prev_close = float(recent[i - 1][1])
                daily_return = round((float(close) - prev_close) / prev_close * 100, 4) if prev_close > 0 else None
            daily.append({"date": td.isoformat(), "close": float(close), "dailyReturnPct": daily_return})
        current = float(recent[-1][1])
        base_close = float(recent[0][1])
        base_date = recent[0][0]
        cum_return = round((current - base_close) / base_close * 100, 4) if base_close > 0 else None
        out.append({
            "name": tgt["name"], "code": tgt["code"], "fullCode": full,
            "current": current, "currentDate": recent[-1][0].isoformat(),
            "baseClose": base_close, "baseDate": base_date.isoformat(),
            "returnPct": cum_return, "daily": daily, "available": True,
        })
    return out


def get_index_returns_as_of(days: int, as_of_date) -> list[dict[str, Any]]:
    if isinstance(as_of_date, str):
        as_of_date = date.fromisoformat(as_of_date)
    days = max(1, min(days, 60))
    rows_needed = days + 1
    out: list[dict[str, Any]] = []
    for tgt in INDEX_TARGETS:
        full = tgt["full"]
        bars = _bars_up_to(full, as_of_date, rows_needed)
        if not bars:
            out.append({
                "name": tgt["name"], "code": tgt["code"], "fullCode": full,
                "current": None, "currentDate": None, "baseClose": None,
                "baseDate": None, "returnPct": None, "daily": [], "available": False,
            })
            continue
        recent = bars[-days:] if len(bars) >= days else bars
        daily: list[dict[str, Any]] = []
        for i, (td, close) in enumerate(recent):
            if i == 0:
                daily_return = None
            else:
                prev_close = float(recent[i - 1][1])
                daily_return = round((float(close) - prev_close) / prev_close * 100, 4) if prev_close > 0 else None
            daily.append({"date": td.isoformat(), "close": float(close), "dailyReturnPct": daily_return})
        current = float(recent[-1][1])
        base_close = float(recent[0][1])
        base_date = recent[0][0]
        cum_return = round((current - base_close) / base_close * 100, 4) if base_close > 0 else None
        out.append({
            "name": tgt["name"], "code": tgt["code"], "fullCode": full,
            "current": current, "currentDate": recent[-1][0].isoformat(),
            "baseClose": base_close, "baseDate": base_date.isoformat(),
            "returnPct": cum_return, "daily": daily, "available": True,
        })
    return out


def coverage_summary() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tgt in INDEX_TARGETS:
        r = query_one(
            "SELECT MIN(trade_date), MAX(trade_date), COUNT(DISTINCT trade_date) FROM index_daily_raw WHERE code = %s",
            (tgt["full"],),
        )
        out.append({
            "name": tgt["name"], "code": tgt["code"], "fullCode": tgt["full"],
            "firstDate": r[0].isoformat() if r and r[0] else None,
            "lastDate": r[1].isoformat() if r and r[1] else None,
            "rowCount": int(r[2]) if r and r[2] else 0,
        })
    return out


def save_index_returns(window_days: int, items: list[dict[str, Any]]) -> int:
    if not items:
        return 0
    n = 0
    with session_scope() as db:
        for it in items:
            if not it.get("available") or it.get("currentDate") is None:
                continue
            td = _to_date(it["currentDate"])
            if td is None:
                continue
            execute_upsert(
                db,
                table="mkt_index_return_daily",
                key_columns=["trade_date", "index_code", "window_days"],
                values={
                    "trade_date": td,
                    "index_code": str(it.get("fullCode") or ""),
                    "index_name": str(it.get("name") or ""),
                    "window_days": int(window_days),
                    "current_close": float(it.get("current") or 0),
                    "current_trade_date": td,
                    "base_close": float(it.get("baseClose") or 0),
                    "base_date": _to_date(it.get("baseDate")) or td,
                    "return_pct": float(it.get("returnPct") or 0),
                    "source": "clickhouse.index_daily_raw",
                    "ingested_at": datetime.now(),
                },
            )
            n += 1
    return n


def get_index_returns_persisted(window_days: int, as_of_date: date | str | None = None) -> list[dict[str, Any] | None] | None:
    with session_scope() as db:
        if as_of_date is not None:
            target = _to_date(as_of_date)
        else:
            target = db.execute(text("SELECT MAX(trade_date) FROM cynexus_appl_market.mkt_index_return_daily WHERE deleted_at IS NULL")).scalar_one_or_none()
        if target is None:
            return None
        rows = db.execute(text("""
            SELECT index_code, index_name, current_close, current_trade_date,
                   base_close, base_date, return_pct
              FROM cynexus_appl_market.mkt_index_return_daily
             WHERE trade_date = :target AND window_days = :window_days AND deleted_at IS NULL
             ORDER BY index_code
        """), {"target": target, "window_days": int(window_days)}).all()
    if not rows:
        return None
    return [{
        "name": r[1],
        "code": _short_code(r[0]),
        "fullCode": r[0],
        "current": float(r[2]),
        "currentDate": r[3].isoformat() if r[3] else None,
        "baseClose": float(r[4]),
        "baseDate": r[5].isoformat() if r[5] else None,
        "returnPct": round(float(r[6]), 4) if r[6] is not None else None,
        "available": True,
        "fromCache": True,
    } for r in rows]


def get_index_returns_history(window_days: int, start: date | str, end: date | str | None = None) -> list[dict[str, Any]]:
    s = _to_date(start)
    e = _to_date(end) if end is not None else s
    if s is None or e is None:
        return []
    with session_scope() as db:
        rows = db.execute(text("""
            SELECT trade_date, index_code, index_name, current_close, current_trade_date,
                   base_close, base_date, return_pct
              FROM cynexus_appl_market.mkt_index_return_daily
             WHERE window_days = :window_days AND trade_date BETWEEN :s AND :e AND deleted_at IS NULL
             ORDER BY trade_date ASC, index_code ASC
        """), {"window_days": int(window_days), "s": s, "e": e}).all()
    return [{
        "tradeDate": r[0].isoformat(),
        "code": _short_code(r[1]),
        "name": r[2],
        "current": float(r[3]) if r[3] is not None else None,
        "currentDate": r[4].isoformat() if r[4] else None,
        "baseClose": float(r[5]) if r[5] is not None else None,
        "baseDate": r[6].isoformat() if r[6] else None,
        "returnPct": round(float(r[7]), 4) if r[7] is not None else None,
    } for r in rows]


def get_index_returns_cached(days: int = 5, *, force: bool = False) -> list[dict[str, Any]]:
    if not force:
        cached = get_index_returns_persisted(days)
        if cached is not None:
            return cached
    items = get_index_returns(days)
    try:
        save_index_returns(days, items)
    except Exception:
        logger.debug("save_index_returns failed", exc_info=True)
    return items


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(coverage_summary(), indent=2, ensure_ascii=False))
    print(_json.dumps(get_index_returns(days=5), indent=2, ensure_ascii=False))
