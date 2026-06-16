"""
历史涨跌停数据读取与均线码计算。

数据源: reference/market-limit/daily/<date>.json

主要接口:
  load_daily_stocks(date)          -> list[StockRow]   读取单日全量数据
  calculate_ma(stock_code, windows) -> dict[window, ma]  计算均线
  calculate_ma_codes(date, windows) -> list[StockMACode]  计算均线码
  get_streak_stats(date)            -> StreakStats        连板统计
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from backend.config.settings import MARKET_LIMIT_DAILY_DIR

# ---------------------------------------------------------------
# 类型定义
# ---------------------------------------------------------------
StockRow = dict[str, Any]

StockMACode = dict[str, Any]

StreakStats = dict[str, Any]

# ---------------------------------------------------------------
# 工具
# ---------------------------------------------------------------
def _read_daily(path: Path) -> list[StockRow]:
    if not path.exists():
        return []
    try:
        import json as _json
        with path.open(encoding="utf-8") as f:
            data = _json.load(f)
        return data.get("stocks") or []
    except Exception:
        return []


# ---------------------------------------------------------------
# 1. 读取单日涨跌停数据
# ---------------------------------------------------------------
def load_daily_stocks(trade_date: date | str) -> list[StockRow]:
    """返回指定交易日所有股票的涨跌停记录（含均线字段）。"""
    if isinstance(trade_date, str):
        trade_date = date.fromisoformat(trade_date)
    path = MARKET_LIMIT_DAILY_DIR / f"{trade_date.isoformat()}.json"
    return _read_daily(path)


# ---------------------------------------------------------------
# 2. 计算单只股票均线
# ---------------------------------------------------------------
def calculate_ma(
    stock_code: str,
    window: int,
    end_date: date | str | None = None,
) -> list[dict]:
    """
    计算指定股票在 end_date 之前 window 天的收盘价均线。

    通过往前读最多 window*2 天的 daily 文件来凑够数据。

    Returns:
        list[{"date": date, "ma": float, "close": float}]
    """
    if isinstance(end_date, str):
        end_date = date.fromisoformat(end_date)
    if end_date is None:
        from datetime import datetime
        end_date = datetime.now().date()

    from backend.services.stock.trading_calendar import previous_trading_day

    # 收集 window*2 天内的交易日（足够算均线）
    dates = []
    p = end_date
    for _ in range(window * 2):
        p = previous_trading_day(p)
        dates.append(p)
    dates.sort()

    # 读取所有相关 daily 文件
    all_rows: dict[date, StockRow] = {}
    for d in dates:
        path = MARKET_LIMIT_DAILY_DIR / f"{d.isoformat()}.json"
        for row in _read_daily(path):
            if row.get("code", "").lower() == stock_code.lower():
                all_rows[d] = row

    # 按日期升序
    sorted_dates = sorted(all_rows.keys())

    # 计算 MA
    result = []
    closes: list[float] = []
    for d in sorted_dates:
        row = all_rows[d]
        close = row.get("latestPrice")
        if close is None:
            continue
        closes.append(float(close))
        if len(closes) > window:
            closes.pop(0)
        if len(closes) == window:
            ma_val = sum(closes) / window
            result.append({
                "date": d,
                "ma": round(ma_val, 4),
                "close": float(close),
            })

    return result


# ---------------------------------------------------------------
# 3. 计算均线码（MA Code）
# 均线码定义：收盘价在 MA 线上 = 1，线下 = 0
# 多均线码 = 各位连接，如 "1110" 表示 10/20/30 MA 线上，60 MA 线下
# ---------------------------------------------------------------
def calculate_ma_codes(
    trade_date: date | str,
    windows: list[int] | tuple[int, ...] = (10, 15, 20, 30, 60, 90, 252),
) -> list[StockMACode]:
    """
    返回所有股票在 trade_date 的均线码。

    均线码 = 各周期 MA 对应的 0/1 序列。
    例如 windows=[10,20,30] 时，返回如:
      {"code": "600519", "name": "贵州茅台", "ma_codes": "110", "close": 1271.1,
       "ma10": 1265.5, "ma20": 1258.3, "ma30": 1247.1}
    """
    if isinstance(trade_date, str):
        trade_date = date.fromisoformat(trade_date)

    rows = load_daily_stocks(trade_date)
    if not rows:
        return []

    # 先收集所有股票的前 window*2 天数据
    from backend.services.stock.trading_calendar import previous_trading_day

    max_window = max(windows)
    needed_dates: list[date] = []
    p = trade_date
    for _ in range(max_window * 2):
        p = previous_trading_day(p)
        needed_dates.append(p)
    needed_dates.sort()

    # 批量加载
    date_rows: dict[date, dict[str, StockRow]] = {}
    for d in needed_dates:
        date_path = MARKET_LIMIT_DAILY_DIR / f"{d.isoformat()}.json"
        date_rows[d] = {}
        for row in _read_daily(date_path):
            date_rows[d][row.get("code", "").lower()] = row

    results = []
    for row in rows:
        code = (row.get("code") or "").lower()
        name = row.get("name") or ""
        close = row.get("latestPrice")
        if not close:
            continue

        ma_vals: dict[int, float | None] = {}
        code_bins = {w: [] for w in windows}

        # 从 trade_date 往前 window 天收集收盘价
        p = trade_date
        for _ in range(max_window):
            p = previous_trading_day(p)
            d_rows = date_rows.get(p, {})
            r = d_rows.get(code)
            if r:
                c = r.get("latestPrice")
                if c:
                    for w in windows:
                        code_bins[w].append(float(c))

        for w in windows:
            vals = code_bins[w]
            if len(vals) >= w:
                ma_vals[w] = round(sum(vals[-w:]) / w, 4)
            else:
                ma_vals[w] = None

        # 拼接均线码（按 windows 顺序）
        ma_code_str = "".join(
            "1" if (ma_vals.get(w) is not None and close >= ma_vals[w]) else "0"
            for w in windows
        )

        result_row: dict[str, Any] = {
            "code": code,
            "name": name,
            "close": float(close),
            "ma_codes": ma_code_str,
        }
        for w in windows:
            result_row[f"ma{w}"] = ma_vals.get(w)

        results.append(result_row)

    return results


# ---------------------------------------------------------------
# 4. 连板统计
# ---------------------------------------------------------------
def get_streak_stats(trade_date: date | str) -> StreakStats:
    """返回指定交易日的连板相关统计。"""
    if isinstance(trade_date, str):
        trade_date = date.fromisoformat(trade_date)

    rows = load_daily_stocks(trade_date)
    if not rows:
        return {"maxStreak": None, "streakDistribution": [], "limitUpCount": 0, "limitDownCount": 0}

    limit_up = [r for r in rows if r.get("isLimitUp")]
    limit_down = [r for r in rows if r.get("isLimitDown")]

    streak_buckets: dict[int, list] = {}
    for r in rows:
        s = r.get("limitUpStreak") or 0
        if s > 0:
            streak_buckets.setdefault(s, []).append(r)

    max_streak = max(streak_buckets.keys()) if streak_buckets else None

    return {
        "tradeDate": trade_date.isoformat(),
        "limitUpCount": len(limit_up),
        "limitDownCount": len(limit_down),
        "maxStreak": max_streak,
        "streakDistribution": [
            {"streak": s, "count": len(stocks), "stocks": [
                {"code": st.get("code"), "name": st.get("name")}
                for st in stocks
            ]}
            for s, stocks in sorted(streak_buckets.items(), reverse=True)
        ],
    }


# ---------------------------------------------------------------
# 5. 批量读取历史区间（用于构建时间序列）
# ---------------------------------------------------------------
def load_date_range(
    start_date: date | str,
    end_date: date | str,
) -> dict[str, list[StockRow]]:
    """返回 start 到 end 之间每个交易日的全量数据。"""
    if isinstance(start_date, str):
        start_date = date.fromisoformat(start_date)
    if isinstance(end_date, str):
        end_date = date.fromisoformat(end_date)

    from backend.services.stock.trading_calendar import next_trading_day

    result: dict[str, list[StockRow]] = {}
    p = start_date
    while p <= end_date:
        rows = load_daily_stocks(p)
        if rows:
            result[p.isoformat()] = rows
        p = next_trading_day(p)

    return result
