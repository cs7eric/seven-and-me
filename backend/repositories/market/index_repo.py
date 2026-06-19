"""宽基指数 K 线查询 (中证1000 / 沪深300).

数据源: duckdb `index_daily_raw` 表 (由 scripts/fetch_index_history.py 落库).
不再走网络 — 走 duckdb 读侧, 历史任意日 O(<100ms) 返回.

指数 code 用 'sh000300' / 'sh000852' 这种带交易所前缀 (与 daily_raw 6 位 code 隔离,
避免与 A股 code 000300 撞码).
"""
from __future__ import annotations

from datetime import date
from typing import Any

from backend.adapters.market.duckdb_store import get_conn
from backend.services.stock.trading_calendar import is_trading_day

import logging
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 关注的宽基指数
# ---------------------------------------------------------------------------
INDEX_TARGETS: list[dict[str, str]] = [
    {"name": "上证指数", "code": "000001", "full": "sh000001", "exchange": "sh"},
    {"name": "沪深300", "code": "000300", "full": "sh000300", "exchange": "sh"},
    {"name": "中证1000", "code": "000852", "full": "sh000852", "exchange": "sh"},
]


def _to_date(v: date | str | None) -> date | None:
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(v)


# ---------------------------------------------------------------------------
# 1. 批量 upsert (给 fetcher 用)
# ---------------------------------------------------------------------------

def upsert_index_daily(code: str, rows: list[dict[str, Any]], source: str = "eastmoney") -> int:
    """批量写入指数日 K. rows 元素含 trade_date / open / high / low / close / volume / amount.

    走 INSERT OR REPLACE (PK = code+trade_date), 重复日期会被覆盖 (适用于增量 + 重跑).
    返回写入行数.
    """
    if not rows:
        return 0
    con = get_conn()
    sql = """
        INSERT OR REPLACE INTO index_daily_raw
            (code, trade_date, open, high, low, close, volume, amount, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    n = 0
    for r in rows:
        td = _to_date(r.get("trade_date") or r.get("date"))
        if td is None:
            continue
        if not is_trading_day(td):
            logger.debug("upsert_index_daily %s skipped non-trading day: %s", code, td)
            continue
        con.execute(sql, [
            code, td,
            float(r.get("open") or 0),
            float(r.get("high") or 0),
            float(r.get("low") or 0),
            float(r.get("close") or 0),
            int(r.get("volume") or 0),
            float(r.get("amount") or 0),
            source,
        ])
        n += 1
    return n


# ---------------------------------------------------------------------------
# 2. 单只指数 K 线 (按 days 拉, 按 trade_date DESC LIMIT, 再升序返回)
# ---------------------------------------------------------------------------

def get_index_daily(code: str, days: int = 30) -> list[dict[str, Any]]:
    """单只指数近 N 个交易日 K 线, 按 trade_date ASC."""
    if not code:
        return []
    days = max(1, min(days, 1500))
    con = get_conn()
    rows = con.execute(
        """
        SELECT code, trade_date, open, high, low, close, volume, amount
          FROM index_daily_raw
         WHERE code = ?
         ORDER BY trade_date DESC
         LIMIT ?
        """,
        [code, days],
    ).fetchall()
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


# ---------------------------------------------------------------------------
# 3. 近 N 日累计收益 (Market Pulse 主用)
# ---------------------------------------------------------------------------

def _bars_up_to(code: str, as_of_date, n: int) -> list[tuple]:
    """取 <= as_of_date 的最近 n 个交易日 K 线 (ASC)."""
    con = get_conn()
    rows = con.execute(
        """
        SELECT trade_date, close
          FROM index_daily_raw
         WHERE code = ? AND trade_date <= ?
         ORDER BY trade_date DESC
         LIMIT ?
        """,
        [code, as_of_date, n],
    ).fetchall()
    return list(reversed(rows))


def get_index_returns(days: int = 5) -> list[dict[str, Any]]:
    """所有 INDEX_TARGETS 近 N 个交易日的累计收益率 (以**最近一个有数据日**为基准).

    Returns:
      [{
        "name": "沪深300",
        "code": "000300",
        "fullCode": "sh000300",
        "current": 3850.12,
        "currentDate": "2026-06-16",
        "baseClose": 3810.45,        # 5 个交易日前的 close
        "baseDate": "2026-06-09",
        "returnPct": 1.04,           # 累计收益 %
        "daily": [
          {"date": "2026-06-09", "close": 3810.45, "dailyReturnPct": null},  # 基准日无收益
          {"date": "2026-06-10", "close": 3820.10, "dailyReturnPct": 0.25},
          ...
        ],
      }, ...]
    """
    days = max(1, min(days, 60))
    # 多取 1 行, 用来算 daily 的首行 (它的 base 没有前一天, daily return = null)
    rows_needed = days + 1

    con = get_conn()
    out: list[dict[str, Any]] = []
    for tgt in INDEX_TARGETS:
        full = tgt["full"]
        bars = con.execute(
            """
            SELECT trade_date, close
              FROM index_daily_raw
             WHERE code = ?
             ORDER BY trade_date DESC
             LIMIT ?
            """,
            [full, rows_needed],
        ).fetchall()
        # bars 按 trade_date DESC, 反转成 ASC
        bars = list(reversed(bars))
        if not bars:
            out.append({
                "name": tgt["name"],
                "code": tgt["code"],
                "fullCode": full,
                "current": None,
                "currentDate": None,
                "baseClose": None,
                "baseDate": None,
                "returnPct": None,
                "daily": [],
                "available": False,
            })
            continue

        # 截取最近 days 个交易日 (剔除最早的 1 个, 用来算 base)
        recent = bars[-days:] if len(bars) >= days else bars
        # daily return: 用 (current / prev_close - 1) * 100
        daily: list[dict[str, Any]] = []
        for i, (td, close) in enumerate(recent):
            if i == 0:
                daily_return = None
            else:
                prev_close = float(recent[i - 1][1])
                if prev_close > 0:
                    daily_return = round((float(close) - prev_close) / prev_close * 100, 4)
                else:
                    daily_return = None
            daily.append({
                "date": td.isoformat(),
                "close": float(close),
                "dailyReturnPct": daily_return,
            })

        # 累计收益: current vs base
        current = float(recent[-1][1])
        base_close = float(recent[0][1])
        base_date = recent[0][0]
        if base_close > 0:
            cum_return = round((current - base_close) / base_close * 100, 4)
        else:
            cum_return = None

        out.append({
            "name": tgt["name"],
            "code": tgt["code"],
            "fullCode": full,
            "current": current,
            "currentDate": recent[-1][0].isoformat(),
            "baseClose": base_close,
            "baseDate": base_date.isoformat(),
            "returnPct": cum_return,
            "daily": daily,
            "available": True,
        })
    return out


def get_index_returns_as_of(days: int, as_of_date) -> list[dict[str, Any]]:
    """以**指定日 as_of_date** 为基准的近 N 日累计收益率 (回填用).

    算法: 取 <= as_of_date 的最近 days+1 天 (含 base 日), 用 (current / base - 1) 算累计.
    跟 get_index_returns() 的差别只在 anchor 点 (用 as_of_date 替代"今天").

    Returns 字段同 get_index_returns, daily 数 = days (含 as_of_date 当天).
    """
    from datetime import date as _date
    if isinstance(as_of_date, str):
        as_of_date = _date.fromisoformat(as_of_date)
    days = max(1, min(days, 60))
    rows_needed = days + 1

    out: list[dict[str, Any]] = []
    for tgt in INDEX_TARGETS:
        full = tgt["full"]
        bars = _bars_up_to(full, as_of_date, rows_needed)
        if not bars:
            out.append({
                "name": tgt["name"],
                "code": tgt["code"],
                "fullCode": full,
                "current": None,
                "currentDate": None,
                "baseClose": None,
                "baseDate": None,
                "returnPct": None,
                "daily": [],
                "available": False,
            })
            continue

        recent = bars[-days:] if len(bars) >= days else bars
        daily: list[dict[str, Any]] = []
        for i, (td, close) in enumerate(recent):
            if i == 0:
                daily_return = None
            else:
                prev_close = float(recent[i - 1][1])
                daily_return = round(
                    (float(close) - prev_close) / prev_close * 100, 4
                ) if prev_close > 0 else None
            daily.append({
                "date": td.isoformat(),
                "close": float(close),
                "dailyReturnPct": daily_return,
            })

        current = float(recent[-1][1])
        base_close = float(recent[0][1])
        base_date = recent[0][0]
        cum_return = round((current - base_close) / base_close * 100, 4) if base_close > 0 else None

        out.append({
            "name": tgt["name"],
            "code": tgt["code"],
            "fullCode": full,
            "current": current,
            "currentDate": recent[-1][0].isoformat(),
            "baseClose": base_close,
            "baseDate": base_date.isoformat(),
            "returnPct": cum_return,
            "daily": daily,
            "available": True,
        })
    return out


# ---------------------------------------------------------------------------
# 4. 覆盖度 (运维用)
# ---------------------------------------------------------------------------

def coverage_summary() -> list[dict[str, Any]]:
    """每只指数的入库覆盖: first_date, last_date, count."""
    con = get_conn()
    out: list[dict[str, Any]] = []
    for tgt in INDEX_TARGETS:
        r = con.execute(
            "SELECT MIN(trade_date), MAX(trade_date), COUNT(*) "
            "FROM index_daily_raw WHERE code = ?",
            [tgt["full"]],
        ).fetchone()
        out.append({
            "name": tgt["name"],
            "code": tgt["code"],
            "fullCode": tgt["full"],
            "firstDate": r[0].isoformat() if r[0] else None,
            "lastDate": r[1].isoformat() if r[1] else None,
            "rowCount": int(r[2]) if r[2] else 0,
        })
    return out


# ---------------------------------------------------------------------------
# 5. 持久化: 累计收益快照 (duckdb.index_returns_daily)
# ---------------------------------------------------------------------------
#
# 设计: cache-aside
#   - save_index_returns(window_days, items) 落盘 get_index_returns 的输出
#   - get_index_returns_persisted(days) 优先查表, 没记录返 None
#   - get_index_returns(days) 改成 cache-aside: 查表, 没记录才现算 + 自动落盘
# ---------------------------------------------------------------------------

def save_index_returns(window_days: int, items: list[dict[str, Any]]) -> int:
    """把 get_index_returns 返回的 items 落盘 (INSERT OR REPLACE).

    items 元素含: name / code / fullCode / current / currentDate / baseClose / baseDate / returnPct
    """
    if not items:
        return 0
    con = get_conn()
    sql = """
        INSERT OR REPLACE INTO index_returns_daily
            (trade_date, index_code, index_name, window_days,
             current, current_date, base_close, base_date, return_pct,
             source, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)
    """
    n = 0
    for it in items:
        if not it.get("available") or it.get("currentDate") is None:
            continue
        td = _to_date(it["currentDate"])
        if td is None:
            continue
        con.execute(sql, [
            td,
            str(it.get("fullCode") or ""),
            str(it.get("name") or ""),
            int(window_days),
            float(it.get("current") or 0),
            td,
            float(it.get("baseClose") or 0),
            _to_date(it.get("baseDate")) or td,
            float(it.get("returnPct") or 0),
            "tencent",
        ])
        n += 1
    return n


def get_index_returns_persisted(
    window_days: int,
    as_of_date: date | str | None = None,
) -> list[dict[str, Any] | None] | None:
    """按 (trade_date, index_code) 查表. as_of_date 默认取 max(trade_date).

    Returns: [ {name, code, fullCode, current, ..., returnPct, fromCache}, ... ] (跟 get_index_returns 同 shape)
             找不到 (表为空 / 找不到目标日) 返 None (让调用方走现算).
    """
    con = get_conn()
    if as_of_date is not None:
        target = _to_date(as_of_date)
    else:
        r = con.execute("SELECT MAX(trade_date) FROM index_returns_daily").fetchone()
        target = r[0] if r and r[0] else None
    if target is None:
        return None
    rows = con.execute("""
        SELECT index_code, index_name, current, current_date,
               base_close, base_date, return_pct
          FROM index_returns_daily
         WHERE trade_date = ? AND window_days = ?
         ORDER BY index_code
    """, [target, int(window_days)]).fetchall()
    if not rows:
        return None
    items: list[dict[str, Any]] = []
    for r in rows:
        cur = float(r[2])
        bc = float(r[4])
        ret = float(r[6]) if r[6] is not None else None
        items.append({
            "name": r[1],
            "code": r[0].lstrip("szh") if r[0] else "",  # 'sh000300' -> '000300'
            "fullCode": r[0],
            "current": cur,
            "currentDate": r[3].isoformat() if r[3] else None,
            "baseClose": bc,
            "baseDate": r[5].isoformat() if r[5] else None,
            "returnPct": round(ret, 4) if ret is not None else None,
            "available": True,
            "fromCache": True,
        })
    return items


def get_index_returns_history(
    window_days: int,
    start: date | str,
    end: date | str | None = None,
) -> list[dict[str, Any]]:
    """区间查 index_returns_daily (按 trade_date ASC, 一日一条 = 全部指数的最近快照).

    实际返回: 每天 = 沪深300 + 中证1000 各一条.
    """
    s = _to_date(start)
    e = _to_date(end) if end is not None else s
    if s is None or e is None:
        return []
    con = get_conn()
    rows = con.execute("""
        SELECT trade_date, index_code, index_name, current, current_date,
               base_close, base_date, return_pct
          FROM index_returns_daily
         WHERE window_days = ? AND trade_date BETWEEN ? AND ?
         ORDER BY trade_date ASC, index_code ASC
    """, [int(window_days), s, e]).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        ret = float(r[7]) if r[7] is not None else None
        out.append({
            "tradeDate": r[0].isoformat(),
            "code": r[1].lstrip("szh") if r[1] else "",
            "name": r[2],
            "current": float(r[3]) if r[3] is not None else None,
            "currentDate": r[4].isoformat() if r[4] else None,
            "baseClose": float(r[5]) if r[5] is not None else None,
            "baseDate": r[6].isoformat() if r[6] else None,
            "returnPct": round(ret, 4) if ret is not None else None,
        })
    return out


# ---------------------------------------------------------------------------
# 6. get_index_returns 改成 cache-aside
# ---------------------------------------------------------------------------

def get_index_returns_cached(days: int = 5, *, force: bool = False) -> list[dict[str, Any]]:
    """cache-aside 版: 优先查 index_returns_daily, 没记录才现算 + 自动落盘.

    Args:
        days: 窗口天数 (5/10/20/60)
        force: True 跳过 cache 重算 + 覆盖 (调算法 / 修复数据后)
    """
    if not force:
        cached = get_index_returns_persisted(days)
        if cached is not None:
            return cached
    items = get_index_returns(days)
    try:
        save_index_returns(days, items)
    except Exception:
        pass
    return items


# ---------------------------------------------------------------------------
# smoke
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json as _json
    print("=== coverage_summary ===")
    print(_json.dumps(coverage_summary(), indent=2, ensure_ascii=False))
    print("\n=== get_index_returns(days=5) ===")
    print(_json.dumps(get_index_returns(days=5), indent=2, ensure_ascii=False))
