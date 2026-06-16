"""日 K 查询 (raw / qfq / hfq).

返回 list[dict] 与现有 StockKlineBar 兼容:
  {timestamp, trade_date, open, high, low, close, volume, amount, adj_factor}

`timestamp` 字段是 ms epoch (Asia/Shanghai 09:30 当日), 与 klinecharts / ECharts
等前端图表库约定一致. 由 trade_date 计算: epoch_ms = (trade_date 09:30 +08:00) * 1000.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone, timedelta
from typing import Any

from backend.adapters.market.duckdb_store import get_conn

_TABLE_BY_ADJUST: dict[str, str] = {
    "none": "daily_raw",
    "qfq": "daily_qfq",
    "hfq": "daily_hfq",
}

_BEIJING_TZ = timezone(timedelta(hours=8))
_TRADE_TS = time(9, 30)  # TDX 默认 K 线时间戳


def _epoch_ms(d: date) -> int:
    """trade_date → 当日 09:30 +08:00 的 ms epoch."""
    return int(datetime.combine(d, _TRADE_TS, tzinfo=_BEIJING_TZ).timestamp() * 1000)


def _row_to_bar(row: tuple, has_adj_factor: bool) -> dict[str, Any]:
    """DuckDB row tuple → StockKlineBar dict."""
    # row order: trade_date, open, high, low, close, volume, amount [, adj_factor]
    td = row[0]
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


def get_daily_kline(
    code: str,
    adjust: str = "qfq",
    start: date | str | None = None,
    end: date | str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """拉取单只股票的日 K.

    Args:
        code: 6 位股票代码 (无交易所前缀)
        adjust: 'qfq' | 'hfq' | 'none'
        start/end: ISO 日期或 date 对象; None 表示不限制
        limit: 限制返回行数 (按 trade_date DESC 取最新 limit 条, 再升序返回)

    Returns:
        list of dict, 按 trade_date ASC 排列. 空列表表示无数据 (代码不存在 / 未入库).
    """
    table = _TABLE_BY_ADJUST.get(adjust)
    if not table:
        raise ValueError(f"invalid adjust: {adjust!r} (use 'qfq' | 'hfq' | 'none')")

    has_adj = table != "daily_raw"
    cols = (
        "trade_date, open, high, low, close, volume, amount, adj_factor"
        if has_adj
        else "trade_date, open, high, low, close, volume, amount"
    )

    where = ["code = ?"]
    params: list[Any] = [code]
    if start is not None:
        where.append("trade_date >= ?")
        params.append(_to_date(start))
    if end is not None:
        where.append("trade_date <= ?")
        params.append(_to_date(end))
    where_sql = " AND ".join(where)

    # limit applied at the SQL level (DESC → ASC after)
    limit_sql = ""
    if limit is not None:
        limit_sql = f" ORDER BY trade_date DESC LIMIT {int(limit)}"
        order_sql = " ORDER BY trade_date ASC"
    else:
        order_sql = " ORDER BY trade_date ASC"

    sql = f"SELECT {cols} FROM {table} WHERE {where_sql}{limit_sql}"
    if limit is not None:
        sql = f"SELECT * FROM ({sql}){order_sql}"

    con = get_conn()
    rows = con.execute(sql, params).fetchall()
    return [_row_to_bar(r, has_adj) for r in rows]


def get_latest_trade_date(code: str) -> date | None:
    """某只股票最近一个有数据的交易日."""
    con = get_conn()
    r = con.execute(
        "SELECT MAX(trade_date) FROM daily_raw WHERE code = ?", [code]
    ).fetchone()
    return r[0] if r and r[0] is not None else None


def has_qfq(code: str) -> bool:
    """该代码是否有任何 qfq 数据. 给 kline_service 做 fallback 判断用."""
    con = get_conn()
    r = con.execute(
        "SELECT EXISTS (SELECT 1 FROM daily_qfq WHERE code = ? LIMIT 1)",
        [code],
    ).fetchone()
    return bool(r[0]) if r else False


def coverage_gap() -> list[dict[str, Any]]:
    """列出 raw 有但 qfq 没数据的代码. 给运维/监控用."""
    con = get_conn()
    rows = con.execute("""
        SELECT r.code, MIN(r.trade_date), MAX(r.trade_date), COUNT(*) AS raw_rows
          FROM daily_raw r
         WHERE NOT EXISTS (
               SELECT 1 FROM daily_qfq q
                WHERE q.code = r.code AND q.trade_date = r.trade_date)
         GROUP BY r.code
         ORDER BY r.code
    """).fetchall()
    return [
        {"code": r[0], "first_date": r[1].isoformat() if r[1] else None,
         "last_date": r[2].isoformat() if r[2] else None, "raw_rows": int(r[3])}
        for r in rows
    ]


def list_codes_with_qfq() -> list[str]:
    """所有有 qfq 数据的代码 (升序). 给 scheduler / 服务做 fallback 集合."""
    con = get_conn()
    rows = con.execute(
        "SELECT DISTINCT code FROM daily_qfq ORDER BY code"
    ).fetchall()
    return [r[0] for r in rows]


def _to_date(v: date | str) -> date:
    if isinstance(v, date):
        return v
    return date.fromisoformat(v)


if __name__ == "__main__":
    # Smoke: 取 000001 最近 5 天 qfq
    import json as _json
    print(_json.dumps(get_daily_kline("000001", adjust="qfq", limit=5), indent=2, ensure_ascii=False))
    print(f"has_qfq('000001') = {has_qfq('000001')}")
    print(f"has_qfq('999999') = {has_qfq('999999')}")
    print(f"latest_trade_date('000001') = {get_latest_trade_date('000001')}")
