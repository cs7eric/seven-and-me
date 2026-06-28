"""连板 / 涨跌停统计, 从 daily_raw 实时算.

复用 stock_meta_repo 的阈值/is_st 推断. 输出 dict 形状与
limit_emotion_service.snapshot_today_daily 的字段兼容.

算法:
  - 用 lag(close) 取 pre_close, 算涨停价 limit_up_price = pre_close * (1 + threshold)
  - close >= limit_up_price * (1 - tol) → is_limit_up (封板)
  - high  >= limit_up_price * (1 - tol) → is_touched  (盘中触板)
  - 连板 streak: ROW_NUMBER 减去前一个非涨停日 ROW_NUMBER 的累加计数
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any

from backend.adapters.market.clickhouse_store import query_rows
from backend.config.database import session_scope
from backend.repositories.market.market_pg_cynexus_repo import execute_upsert
from backend.repositories.market.percentile_helper import percentile_score
from backend.services.stock.trading_calendar import is_trading_day
from backend.repositories.market.stock_meta_repo import (
    get_threshold,
    is_st_by_name,
    list_universe,
)

logger = logging.getLogger(__name__)


class _ClickHouseResult:
    def __init__(self, rows: list[tuple[Any, ...]]):
        self._rows = rows

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None


class _ClickHouseCompatConn:
    def execute(self, sql: str, params: list[Any] | tuple[Any, ...] | None = None) -> _ClickHouseResult:
        rows = query_rows(sql.replace("?", "%s"), tuple(params or ()))
        return _ClickHouseResult(rows)


@contextmanager
def conn(read_only: bool = False):
    yield _ClickHouseCompatConn()


def get_conn(read_only: bool = False) -> _ClickHouseCompatConn:
    return _ClickHouseCompatConn()

_TOL = 0.0001   # 涨跌停判定容差 (与 limit_emotion_service 一致)
_HIGH_TOL = 0.0005  # 盘中触板容差


# ---------------------------------------------------------------------------
# 1. 单只股票连板历史
# ---------------------------------------------------------------------------

def get_limit_streak_history(
    code: str,
    start: date | str | None = None,
    end: date | str | None = None,
    tolerance: float = _TOL,
) -> list[dict[str, Any]]:
    """返回 [{trade_date, open, high, low, close, pre_close,
              limit_up_price, change_pct,
              is_limit_up, is_touched, is_broken, streak}, ...] 按 trade_date ASC."""
    where = ["r.code = ?"]
    params: list[Any] = [code]
    if start is not None:
        where.append("r.trade_date >= ?")
        params.append(_to_date(start))
    if end is not None:
        where.append("r.trade_date <= ?")
        params.append(_to_date(end))
    where_sql = " AND ".join(where)

    # is_st 走 stock_meta_repo; threshold 也是
    meta = _meta_for_sql(code)
    is_st = 1 if meta["is_st"] else 0
    threshold = meta["threshold"]

    # SQL: 一次扫 daily_raw, 算 limit_up_price / is_limit_up / streak
    # streak 算法 (gaps-and-islands):
    #   group_id = ROW_NUMBER() OVER (ORDER BY trade_date) -
    #              ROW_NUMBER() OVER (PARTITION BY is_limit_up ORDER BY trade_date)
    #   streak   = COUNT(*) OVER (PARTITION BY group_id) WHEN is_limit_up = 1 ELSE 0
    sql = f"""
        WITH base AS (
          SELECT r.code, r.trade_date, r.open, r.high, r.low, r.close, r.volume,
                 lag(r.close) OVER w_ AS pre_close
            FROM daily_raw r
           WHERE {where_sql}
           WINDOW w_ AS (PARTITION BY r.code ORDER BY r.trade_date)
        ),
        flag AS (
          SELECT code, trade_date, open, high, low, close, volume, pre_close,
                 CASE WHEN pre_close IS NULL OR pre_close = 0 THEN NULL
                      ELSE pre_close * (1 + {threshold}) END AS limit_up_price,
                 CASE WHEN pre_close IS NULL OR pre_close = 0 THEN NULL
                      WHEN close >= pre_close * (1 + {threshold}) * (1 - {tolerance})
                      THEN 1 ELSE 0 END AS is_limit_up,
                 CASE WHEN pre_close IS NULL OR pre_close = 0 THEN NULL
                      WHEN high >= pre_close * (1 + {threshold}) * (1 - {_HIGH_TOL})
                      THEN 1 ELSE 0 END AS is_touched
            FROM base
        ),
        islands AS (
          SELECT *,
                 ROW_NUMBER() OVER (PARTITION BY code ORDER BY trade_date) -
                 ROW_NUMBER() OVER (PARTITION BY code, is_limit_up ORDER BY trade_date) AS grp
            FROM flag
        )
        SELECT trade_date, open, high, low, close, volume,
               pre_close, limit_up_price,
               CASE WHEN pre_close IS NULL OR pre_close = 0 THEN NULL
                    ELSE (close - pre_close) / pre_close * 100 END AS change_pct,
               is_limit_up, is_touched,
               CASE WHEN is_limit_up = 0 AND
                         lag(is_limit_up) OVER (PARTITION BY code ORDER BY trade_date) = 1
                    THEN 1 ELSE 0 END AS is_broken,
               CASE WHEN is_limit_up = 1
                    THEN COUNT(*) OVER (PARTITION BY code, grp)
                    ELSE 0 END AS streak
          FROM islands
         ORDER BY trade_date ASC
    """
    # 注: is_broken 简化处理 — 真实的 "炸板" 判定需要今天的 high >= limit 但 close < limit
    # 这里只在 streak 重置时标 1, 用于分布统计

    con = get_conn()
    rows = con.execute(sql, params).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "trade_date": r[0].isoformat(),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": int(r[5]),
            "pre_close": float(r[6]) if r[6] is not None else None,
            "limit_up_price": float(r[7]) if r[7] is not None else None,
            "change_pct": float(r[8]) if r[8] is not None else None,
            "is_limit_up": bool(r[9]) if r[9] is not None else None,
            "is_touched": bool(r[10]) if r[10] is not None else None,
            "is_broken": bool(r[11]) if r[11] is not None else False,
            "streak": int(r[12]) if r[12] is not None else 0,
        })
    return out


# ---------------------------------------------------------------------------
# 2. 单日全市场快照
# ---------------------------------------------------------------------------

def get_today_limit_snapshot(date_: date | str) -> list[dict[str, Any]]:
    """指定日所有 (活跃) 股票的涨跌停快照.

    返回字段 (与 limit_emotion_service.snapshot_today_daily 单条 shape 对齐):
      {code, name, latestPrice, highPrice, limitUpPrice, changePct,
       isLimitUp, isTouchedLimitUp, isBrokenLimitUp, previousLimitUpStreak,
       limitUpStreak, isPromoted, isBrokenStreak}

    字段命名用 camelCase 以兼容前端 MarketLimitRow 接口.
    """
    td = _to_date(date_)
    assert td is not None

    # 拿所有 (or 活跃) 股票
    universe = list_universe(active_only=True)
    if not universe:
        return []

    # 单次 SQL: 对所有 code 在指定日算 is_limit_up + limit_up_streak (含昨日)
    # 用 daily_raw 全表 JOIN, 然后按 code group by 取 max(streak) ≤ td
    codes = [u["code"] for u in universe]

    # 由于 universe 5530 只, 分批查避免单 SQL 过长
    out: list[dict[str, Any]] = []
    BATCH = 1000
    meta_by_code = {u["code"]: u for u in universe}
    for i in range(0, len(codes), BATCH):
        batch = codes[i:i + BATCH]
        out.extend(_snapshot_batch(batch, td, meta_by_code))

    # 按 streak 倒序排
    out.sort(key=lambda x: (-(x.get("limitUpStreak") or 0), x["code"]))
    return out


def _snapshot_batch(
    codes: list[str],
    td: date,
    meta_by_code: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """对一个 batch 的 code 在 td 算 limit snapshot."""
    return _snapshot_python(codes, td, meta_by_code)


def _snapshot_python(
    codes: list[str],
    td: date,
    meta_by_code: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """取 td 当日 OHLC, 在 Python 端查最近 60 天历史算 streak.

    性能: 5500 只 × 60 天 × lag = 单次 ClickHouse 扫几十万行.
    """
    con = get_conn()
    placeholders = ",".join(["?"] * len(codes))

    # 今天 OHLC + pre_close.
    today_rows = con.execute(f"""
        SELECT code, open, high, low, close, volume, pre_close
          FROM (
            SELECT code, trade_date, open, high, low, close, volume,
                   lag(close, 1) OVER (PARTITION BY code ORDER BY trade_date) AS pre_close
              FROM daily_raw
             WHERE code IN ({placeholders}) AND trade_date <= ?
          )
         WHERE trade_date = ?
    """, [*codes, td, td]).fetchall()
    today_by_code = {r[0]: r for r in today_rows}
    if not today_by_code:
        return []

    # 限定到最近 90 天, 避免扫全历史 (28M 行). 60 个交易日足够覆盖绝大多数连板.
    from datetime import timedelta
    history_start = td - timedelta(days=120)
    raw_history = con.execute(f"""
        SELECT code, trade_date, close, pre_close
          FROM (
            SELECT code, trade_date, close,
                   lag(close, 1) OVER (PARTITION BY code ORDER BY trade_date) AS pre_close
              FROM daily_raw
             WHERE code IN ({placeholders}) AND trade_date >= ? AND trade_date < ?
          )
         ORDER BY code, trade_date
    """, [*codes, history_start, td]).fetchall()

    # 按 code 分组 (按 trade_date ASC)
    from collections import defaultdict
    hist_by_code: dict[str, list[tuple]] = defaultdict(list)
    for r in raw_history:
        hist_by_code[r[0]].append(r)
    for v in hist_by_code.values():
        v.sort(key=lambda x: x[1])

    prev_streak_by_code: dict[str, int] = {}
    for code, rows in hist_by_code.items():
        meta = meta_by_code.get(code, {})
        thr = float(meta.get("threshold", 0.10))
        if not rows:
            prev_streak_by_code[code] = 0
            continue
        last_close = float(rows[-1][2])
        last_pre = float(rows[-1][3]) if rows[-1][3] is not None else None
        if last_pre is None or last_pre == 0:
            prev_streak_by_code[code] = 0
            continue
        if last_close >= last_pre * (1 + thr) * (1 - _TOL):
            cur_streak = 0
            for r in reversed(rows):
                c = float(r[2])
                pc = float(r[3]) if r[3] is not None else None
                if pc is None or pc == 0:
                    break
                if c >= pc * (1 + thr) * (1 - _TOL):
                    cur_streak += 1
                else:
                    break
            prev_streak_by_code[code] = cur_streak
        else:
            prev_streak_by_code[code] = 0

    out: list[dict[str, Any]] = []
    for code, row in today_by_code.items():
        meta = meta_by_code.get(code, {})
        thr = float(meta.get("threshold", 0.10))
        name = meta.get("name", "")
        is_st_flag = meta.get("is_st", False)
        open_p = float(row[1])
        high_p = float(row[2])
        low_p = float(row[3])
        close_p = float(row[4])
        vol = int(row[5])
        pre_close = float(row[6]) if row[6] is not None else None
        if pre_close is None or pre_close == 0:
            continue
        limit_up_price = pre_close * (1 + thr)
        limit_down_price = pre_close * (1 - thr)
        is_limit_up = close_p >= limit_up_price * (1 - _TOL)
        is_limit_down = close_p <= limit_down_price * (1 + _TOL)
        is_touched = high_p >= limit_up_price * (1 - _HIGH_TOL)
        is_broken_limit_up = is_touched and not is_limit_up
        prev_streak = prev_streak_by_code.get(code, 0)
        cur_streak = prev_streak + 1 if is_limit_up else 0
        is_promoted = is_limit_up and prev_streak > 0
        is_broken_streak = (not is_limit_up) and prev_streak > 0
        out.append({
            "code": code,
            "name": name,
            "isST": is_st_flag,
            "latestPrice": close_p,
            "highPrice": high_p,
            "lowPrice": low_p,
            "openPrice": open_p,
            "volume": vol,
            "limitUpPrice": round(limit_up_price, 4),
            "limitDownPrice": round(limit_down_price, 4),
            "changePct": round((close_p - pre_close) / pre_close * 100, 2),
            "isLimitUp": is_limit_up,
            "isLimitDown": is_limit_down,
            "isTouchedLimitUp": is_touched,
            "isBrokenLimitUp": is_broken_limit_up,
            "previousLimitUpStreak": prev_streak,
            "limitUpStreak": cur_streak,
            "isPromoted": is_promoted,
            "isBrokenStreak": is_broken_streak,
            "tradeDate": td.isoformat(),
        })
    return out


# ---------------------------------------------------------------------------
# 3. 连板分布 (单日)
# ---------------------------------------------------------------------------

def get_limit_streak_distribution(date_: date | str) -> dict[str, Any]:
    """返回 {maxHeight, leaders, distribution, broken, promoted}.

    与 limit_emotion_service.calculate_streak 字段对齐.
    """
    snap = get_today_limit_snapshot(date_)
    if not snap:
        return {
            "maxHeight": 0, "leaders": [], "distribution": [],
            "broken": {"count": 0, "stocks": []},
            "promoted": {"overallRate": None, "levels": []},
        }

    # distribution: {streak: count}
    from collections import defaultdict
    dist: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in snap:
        s = row["limitUpStreak"]
        if s > 0:
            dist[s].append({"code": row["code"], "name": row["name"]})

    distribution = [
        {"streak": s, "count": len(items), "stocks": items}
        for s, items in sorted(dist.items(), key=lambda x: -x[0])
    ]

    max_height = max(dist.keys(), default=0)
    leaders = dist.get(max_height, [])

    # broken
    broken_rows = [r for r in snap if r["isBrokenStreak"]]
    broken = {
        "count": len(broken_rows),
        "highStreakBrokenCount": sum(1 for r in broken_rows if r["previousLimitUpStreak"] >= 3),
        "stocks": [
            {"code": r["code"], "name": r["name"], "previousStreak": r["previousLimitUpStreak"],
             "changePct": r["changePct"]}
            for r in broken_rows
        ],
    }

    # promoted: 按前一天 streak 分桶
    from collections import Counter
    prev_counts = Counter(r["previousLimitUpStreak"] for r in snap if r["previousLimitUpStreak"] > 0)
    promoted_rows = [r for r in snap if r["isPromoted"]]
    promoted_counts = Counter(r["previousLimitUpStreak"] for r in promoted_rows)
    levels = []
    for s in sorted(prev_counts.keys()):
        y = prev_counts[s]
        p = promoted_counts.get(s, 0)
        levels.append({"from": s, "to": s + 1, "yesterdayCount": y,
                        "todayPromotedCount": p,
                        "rate": round(p / y * 100, 2) if y > 0 else None})
    overall = (sum(promoted_counts.values()) / sum(prev_counts.values()) * 100
               if sum(prev_counts.values()) > 0 else None)

    return {
        "tradeDate": snap[0]["tradeDate"] if snap else None,
        "maxHeight": max_height,
        "leaders": leaders,
        "distribution": distribution,
        "broken": broken,
        "promoted": {"overallRate": round(overall, 2) if overall is not None else None,
                     "levels": levels},
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _meta_for_sql(code: str) -> dict[str, Any]:
    """Local is_st + threshold for SQL-side use. Avoids depending on stock_meta_repo."""
    from backend.repositories.market.stock_meta_repo import (
        get_stock_meta, get_threshold, get_board_type,
    )
    meta = get_stock_meta(code)
    is_st = meta.get("is_st", False) if meta else False
    thr = meta.get("threshold") if meta else None
    if thr is None:
        thr = get_threshold(code, is_st)
    return {"is_st": is_st, "threshold": thr}


def _to_date(v: date | str) -> date:
    if isinstance(v, date):
        return v
    return date.fromisoformat(v)


# ---------------------------------------------------------------------------
# 4. 涨跌停情绪综合分 (limit emotion summary)
#
# 所有子项和总分均采用历史分位 (percentile_score, 见 percentile_helper.py):
#   up_down_score       = percentile(limit_up_down_ratio)              ∈ [0, 100]
#   break_board_score   = 100 - percentile(break_board_rate)           ∈ [0, 100]   (反向)
#   yesterday_return_score = percentile(yesterday_limit_up_avg_return) ∈ [0, 100]
#   composite           = percentile(0.4*A + 0.3*B + 0.3*C)           ∈ [0, 100]
#
# 数据源: 全部用 limit_repo 现有的 snapshot (get_today_limit_snapshot),
#   不直接查 daily_raw, 跟 limit_emotion_service._assemble_from_duckdb
#   路径共用同一份 limit_repo 算出的字段, 避免两边算法漂移.
#
# v2026-06-18: 从固定公式改为历史分位, 自动适应市场环境, 解决原公式
#   在涨跌停比极大时饱和到 100 的问题.
# ---------------------------------------------------------------------------

def _score_up_down(ratio: float | None) -> float:
    """涨跌停比 → 0-100 得分. 1.0 锚定 50, 翻倍 4.0 锚定 75, 0 锚定 0."""
    if ratio is None or ratio <= 0:
        return 0.0
    import math
    return round(max(0.0, min(100.0, 50.0 + 25.0 * math.log2(ratio))), 2)


def _score_break_board(rate: float | None) -> float:
    """炸板率 → 0-100 得分 (反向). 0% → 100, 50% → 50, 100% → 0."""
    if rate is None:
        return 50.0  # 无触板数据兜底中性
    return round(max(0.0, min(100.0, 100.0 - 100.0 * rate)), 2)


def _score_yesterday_return(avg_return_pct: float | None) -> float:
    """昨日涨停股今日平均收益 → 0-100 得分. 0% → 50, +5% → 100, -5% → 0."""
    if avg_return_pct is None:
        return 50.0
    return round(max(0.0, min(100.0, 50.0 + 10.0 * avg_return_pct)), 2)


def _level_for(composite: float) -> str:
    if composite >= 80:
        return "hot"
    if composite >= 60:
        return "active"
    if composite >= 40:
        return "normal"
    if composite >= 20:
        return "weak"
    return "ice"


def calc_limit_emotion_summary(
    trade_date: date | str,
    prev_trade_date: date | str | None = None,
) -> dict[str, Any]:
    """算 limit-emotion-summary 在 trade_date 的所有指标 + composite + level.

    Args:
        trade_date: 主交易日
        prev_trade_date: 上一交易日 (用于算 "昨日涨停股今日平均收益").
            None 时自动从 trading_calendar.previous_trading_day 推断.

    Returns:
      {
        "tradeDate": "2026-06-12",
        "prevTradeDate": "2026-06-11",
        "limitUpCount": 93,
        "limitDownCount": 0,
        "touchedCount": 284,
        "brokenCount": 191,
        "breakBoardRate": 0.6725,         # broken / touched
        "limitUpDownRatio": 93.0,         # limit_up / max(limit_down, 1)
        "yesterdayLimitUpCount": 80,      # 昨日 isLimitUp=True 数量
        "yesterdayLimitUpAvgReturn": -0.76,  # 昨日涨停股今日 changePct 平均 (%)
        "components": {
          "upDownScore": 79.97,
          "breakBoardScore": 32.75,
          "yesterdayReturnScore": 42.4,
        },
        "compositeScore": 50.78,
        "level": "normal",
        "elapsedMs": 1234,
        "source": "clickhouse.daily_raw"
      }
    """
    td = _to_date(trade_date)
    assert td is not None
    if prev_trade_date is None:
        try:
            from backend.services.stock.trading_calendar import previous_trading_day
            prev = previous_trading_day(td)
        except Exception:
            prev = None
    else:
        prev = _to_date(prev_trade_date)

    t0 = time.time()

    # 1) 今日 snapshot
    snap_today = get_today_limit_snapshot(td)
    if not snap_today:
        return {
            "tradeDate": td.isoformat(),
            "prevTradeDate": prev.isoformat() if prev else None,
            "limitUpCount": 0,
            "limitDownCount": 0,
            "touchedCount": 0,
            "brokenCount": 0,
            "breakBoardRate": None,
            "limitUpDownRatio": 0.0,
            "yesterdayLimitUpCount": 0,
            "yesterdayLimitUpAvgReturn": None,
            "components": {
                "upDownScore": 0.0,
                "breakBoardScore": 50.0,
                "yesterdayReturnScore": 50.0,
            },
            "compositeScore": 30.0,
            "level": "weak",
            "elapsedMs": int((time.time() - t0) * 1000),
            "source": "clickhouse.daily_raw",
        }

    limit_up_count = sum(1 for r in snap_today if r.get("isLimitUp"))
    limit_down_count = sum(1 for r in snap_today if r.get("isLimitDown"))
    touched_count = sum(1 for r in snap_today if r.get("isTouchedLimitUp"))
    broken_count = sum(1 for r in snap_today if r.get("isBrokenLimitUp"))
    break_board_rate = (
        round(broken_count / touched_count, 4) if touched_count > 0 else None
    )
    limit_up_down_ratio = round(limit_up_count / max(limit_down_count, 1), 4)

    # 2) 昨日涨停股 ∩ 今日 changePct 均值
    yest_limit_up_count = 0
    yest_avg_return: float | None = None
    if prev is not None:
        snap_yest = get_today_limit_snapshot(prev)
        if snap_yest:
            yest_codes = {r["code"] for r in snap_yest if r.get("isLimitUp")}
            yest_limit_up_count = len(yest_codes)
            today_by_code = {r["code"]: r for r in snap_today}
            returns: list[float] = []
            for code in yest_codes:
                r = today_by_code.get(code)
                if r and r.get("changePct") is not None:
                    returns.append(float(r["changePct"]))
            if returns:
                yest_avg_return = round(sum(returns) / len(returns), 4)

    # 3) sub-scores via historical percentile rank (v2026-06-18)
    #    回退: 历史数据不足时用旧固定公式.
    _TABLE = "limit_emotion_summary_daily"

    up_down_score = _score_up_down(limit_up_down_ratio)  # fallback
    ud_pct = percentile_score(_TABLE, "limit_up_down_ratio", td, limit_up_down_ratio)
    if ud_pct is not None:
        up_down_score = ud_pct

    break_board_score = _score_break_board(break_board_rate)  # fallback
    if break_board_rate is not None:
        bb_pct = percentile_score(_TABLE, "break_board_rate", td, break_board_rate)
        if bb_pct is not None:
            break_board_score = round(100.0 - bb_pct, 2)  # 反向: 高炸板率=低分

    yesterday_return_score = _score_yesterday_return(yest_avg_return)  # fallback
    if yest_avg_return is not None:
        yr_pct = percentile_score(_TABLE, "yesterday_limit_up_avg_return", td, float(yest_avg_return))
        if yr_pct is not None:
            yesterday_return_score = yr_pct

    # composite = weighted average of 3 percentile scores, then percentile-ranked
    composite_raw = round(0.4 * up_down_score + 0.3 * break_board_score + 0.3 * yesterday_return_score, 2)
    composite_pct = percentile_score(_TABLE, "composite_score", td, composite_raw)
    composite_score = composite_pct if composite_pct is not None else composite_raw
    level = _level_for(composite_score)

    elapsed_ms = int((time.time() - t0) * 1000)
    return {
        "tradeDate": td.isoformat(),
        "prevTradeDate": prev.isoformat() if prev else None,
        "limitUpCount": limit_up_count,
        "limitDownCount": limit_down_count,
        "touchedCount": touched_count,
        "brokenCount": broken_count,
        "breakBoardRate": break_board_rate,
        "limitUpDownRatio": limit_up_down_ratio,
        "yesterdayLimitUpCount": yest_limit_up_count,
        "yesterdayLimitUpAvgReturn": yest_avg_return,
        "components": {
            "upDownScore": up_down_score,
            "breakBoardScore": break_board_score,
            "yesterdayReturnScore": yesterday_return_score,
        },
        "compositeScore": composite_score,
        "level": level,
        "elapsedMs": elapsed_ms,
        "source": "clickhouse.daily_raw",
    }


def save_limit_emotion_summary(payload: dict) -> None:
    """把 calc_limit_emotion_summary 的 dict 落盘到 PostgreSQL msi_limit_emotion_daily."""
    td = _to_date(payload.get("tradeDate"))
    if td is None:
        raise ValueError("payload.tradeDate required")
    if not is_trading_day(td):
        logger.debug("save_limit_emotion_summary skipped non-trading day: %s", td)
        return
    comp = payload.get("components") or {}
    yest_avg = payload.get("yesterdayLimitUpAvgReturn")
    bb_rate = payload.get("breakBoardRate")
    ratio = payload.get("limitUpDownRatio")
    with session_scope() as db:
        execute_upsert(db, table="msi_limit_emotion_daily", key_columns=["trade_date"], values={
            "trade_date": td,
            "limit_up_count": int(payload.get("limitUpCount") or 0),
            "limit_down_count": int(payload.get("limitDownCount") or 0),
            "touched_count": int(payload.get("touchedCount") or 0),
            "broken_count": int(payload.get("brokenCount") or 0),
            "break_board_rate": float(bb_rate) if bb_rate is not None else 0.0,
            "limit_up_down_ratio": float(ratio) if ratio is not None else 0.0,
            "yesterday_limit_up_count": int(payload.get("yesterdayLimitUpCount") or 0),
            "yesterday_limit_up_avg_return": float(yest_avg) if yest_avg is not None else 0.0,
            "up_down_score": float(comp.get("upDownScore") or 0),
            "break_board_score": float(comp.get("breakBoardScore") or 0),
            "yesterday_return_score": float(comp.get("yesterdayReturnScore") or 0),
            "composite_score": float(payload.get("compositeScore") or 0),
            "level": str(payload.get("level") or "normal"),
            "elapsed_ms": int(payload.get("elapsedMs") or 0),
            "source": str(payload.get("source") or "clickhouse.daily_raw"),
            "ingested_at": datetime.now(),
        })


_LIMIT_EMOTION_SUMMARY_COLS = (
    "trade_date", "limit_up_count", "limit_down_count", "touched_count", "broken_count",
    "break_board_rate", "limit_up_down_ratio",
    "yesterday_limit_up_count", "yesterday_limit_up_avg_return",
    "up_down_score", "break_board_score", "yesterday_return_score",
    "composite_score", "level",
    "elapsed_ms", "source",
)
_LIMIT_EMOTION_SUMMARY_SELECT = ", ".join(_LIMIT_EMOTION_SUMMARY_COLS)


def _row_to_summary_payload(row: tuple) -> dict:
    """duckdb 行 → calc_limit_emotion_summary 同 shape dict."""
    bb_rate = float(row[5]) if row[5] is not None else None
    ratio = float(row[6]) if row[6] is not None else None
    yest_avg = float(row[8]) if row[8] is not None else None
    return {
        "tradeDate": row[0].isoformat(),
        "prevTradeDate": None,  # 表里不存, 读时按需重新算
        "limitUpCount": int(row[1]),
        "limitDownCount": int(row[2]),
        "touchedCount": int(row[3]),
        "brokenCount": int(row[4]),
        "breakBoardRate": bb_rate,
        "limitUpDownRatio": ratio if ratio is not None
                            else round(int(row[1]) / max(int(row[2]), 1), 4),
        "yesterdayLimitUpCount": int(row[7]),
        "yesterdayLimitUpAvgReturn": yest_avg,
        "components": {
            "upDownScore": float(row[9]),
            "breakBoardScore": float(row[10]),
            "yesterdayReturnScore": float(row[11]),
        },
        "compositeScore": float(row[12]),
        "level": str(row[13]),
        "elapsedMs": int(row[14]) if row[14] is not None else None,
        "source": str(row[15]),
        "fromCache": True,
    }


def get_limit_emotion_summary(trade_date: date | str) -> dict | None:
    """按日期查 msi_limit_emotion_daily. 无记录返 None (不抛)."""
    td = _to_date(trade_date)
    if td is None:
        return None
    with session_scope() as db:
        r = db.execute(__import__("sqlalchemy").text(
            f"SELECT {_LIMIT_EMOTION_SUMMARY_SELECT} FROM cynexus_appl_market.msi_limit_emotion_daily WHERE trade_date = :td AND deleted_at IS NULL LIMIT 1"
        ), {"td": td}).first()
    return _row_to_summary_payload(r) if r else None


def get_limit_emotion_summary_history(
    start: date | str,
    end: date | str | None = None,
) -> list[dict]:
    """区间查 msi_limit_emotion_daily (按 trade_date ASC), 一日一条."""
    s = _to_date(start)
    e = _to_date(end) if end is not None else s
    if s is None or e is None:
        return []
    with session_scope() as db:
        rows = db.execute(__import__("sqlalchemy").text(
            f"SELECT {_LIMIT_EMOTION_SUMMARY_SELECT} FROM cynexus_appl_market.msi_limit_emotion_daily WHERE trade_date BETWEEN :s AND :e AND deleted_at IS NULL ORDER BY trade_date ASC"
        ), {"s": s, "e": e}).all()
    return [_row_to_summary_payload(r) for r in rows]


def calc_limit_emotion_summary_cached(
    trade_date: date | str,
    *,
    force: bool = False,
) -> dict:
    """cache-aside 版: 优先查 limit_emotion_summary_daily, 没记录才现算 + 自动落盘.

    Args:
        trade_date: 目标日
        force: True 跳过 cache 重算 + 覆盖 (维护用)
    """
    if not force:
        cached = get_limit_emotion_summary(trade_date)
        if cached is not None:
            return cached
    payload = calc_limit_emotion_summary(trade_date)
    try:
        save_limit_emotion_summary(payload)
    except Exception:
        pass
    return payload


# ---------------------------------------------------------------------------
# smoke
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json as _json
    print("=== calc_limit_emotion_summary(2026-06-12) ===")
    out = calc_limit_emotion_summary("2026-06-12")
    print(_json.dumps(out, ensure_ascii=False, indent=2))
    print()
    print("=== save + get round-trip ===")
    save_limit_emotion_summary(out)
    cached = get_limit_emotion_summary("2026-06-12")
    print(_json.dumps(cached, ensure_ascii=False, indent=2))
    print(f"fromCache: {cached.get('fromCache')}")

