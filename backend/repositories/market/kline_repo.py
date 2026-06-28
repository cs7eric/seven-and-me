"""日 K 查询 (raw / qfq / hfq) — ClickHouse backend.

返回 list[dict] 与现有 StockKlineBar 兼容:
  {timestamp, trade_date, open, high, low, close, volume, amount, adj_factor}
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone, timedelta
from typing import Any

from backend.adapters.market.clickhouse_store import query_one, query_rows

_TABLE_BY_ADJUST: dict[str, str] = {
    "none": "daily_raw",
    "qfq": "daily_qfq",
    "hfq": "daily_hfq",
}

_BEIJING_TZ = timezone(timedelta(hours=8))
_TRADE_TS = time(9, 30)


def _epoch_ms(d: date) -> int:
    return int(datetime.combine(d, _TRADE_TS, tzinfo=_BEIJING_TZ).timestamp() * 1000)


def _row_to_bar(row: tuple, has_adj_factor: bool) -> dict[str, Any]:
    td = row[0]
    if hasattr(td, "date") and not isinstance(td, date):
        td = td.date()
    out: dict[str, Any] = {
        "timestamp": _epoch_ms(td),
        "trade_date": td.isoformat(),
        "open": float(row[1]),
        "high": float(row[2]),
        "low": float(row[3]),
        "close": float(row[4]),
        "volume": int(row[5]),
        "amount": float(row[6]),
    }
    if has_adj_factor:
        out["adj_factor"] = float(row[7]) if row[7] is not None else 1.0
    return out


def _to_date(v: date | str) -> date:
    if isinstance(v, date):
        return v
    return date.fromisoformat(v)


def get_daily_kline(
    code: str,
    adjust: str = "qfq",
    start: date | str | None = None,
    end: date | str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    table = _TABLE_BY_ADJUST.get(adjust)
    if not table:
        raise ValueError(f"invalid adjust: {adjust!r} (use 'qfq' | 'hfq' | 'none')")

    has_adj = table != "daily_raw"
    cols = (
        "trade_date, open, high, low, close, volume, amount, adj_factor"
        if has_adj
        else "trade_date, open, high, low, close, volume, amount"
    )

    where = ["code = %s"]
    params: list[Any] = [code]
    if start is not None:
        where.append("trade_date >= %s")
        params.append(_to_date(start))
    if end is not None:
        where.append("trade_date <= %s")
        params.append(_to_date(end))
    where_sql = " AND ".join(where)

    if limit is not None:
        sql = f"SELECT {cols} FROM (SELECT {cols} FROM {table} WHERE {where_sql} ORDER BY trade_date DESC LIMIT %s) ORDER BY trade_date ASC"
        params.append(int(limit))
    else:
        sql = f"SELECT {cols} FROM {table} WHERE {where_sql} ORDER BY trade_date ASC"

    rows = query_rows(sql, tuple(params))
    return [_row_to_bar(r, has_adj) for r in rows]


def get_latest_trade_date(code: str) -> date | None:
    row = query_one("SELECT MAX(trade_date) FROM daily_raw WHERE code = %s", (code,))
    return row[0] if row and row[0] is not None else None


def has_qfq(code: str) -> bool:
    row = query_one("SELECT count() > 0 FROM daily_qfq WHERE code = %s LIMIT 1", (code,))
    return bool(row[0]) if row else False


def coverage_gap() -> list[dict[str, Any]]:
    rows = query_rows("""
        SELECT r.code, MIN(r.trade_date), MAX(r.trade_date), COUNT(*) AS raw_rows
          FROM daily_raw r
         WHERE NOT EXISTS (
               SELECT 1 FROM daily_qfq q
                WHERE q.code = r.code AND q.trade_date = r.trade_date)
         GROUP BY r.code
         ORDER BY r.code
    """)
    return [
        {"code": r[0], "first_date": r[1].isoformat() if r[1] else None,
         "last_date": r[2].isoformat() if r[2] else None, "raw_rows": int(r[3])}
        for r in rows
    ]


def list_codes_with_qfq() -> list[str]:
    rows = query_rows("SELECT DISTINCT code FROM daily_qfq ORDER BY code")
    return [r[0] for r in rows]


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(get_daily_kline("000001", adjust="qfq", limit=5), indent=2, ensure_ascii=False))
    print(f"has_qfq('000001') = {has_qfq('000001')}")
    print(f"has_qfq('999999') = {has_qfq('999999')}")
    print(f"latest_trade_date('000001') = {get_latest_trade_date('000001')}")
