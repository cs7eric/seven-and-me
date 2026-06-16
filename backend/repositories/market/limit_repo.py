"""连板 / 涨跌停统计, 从 daily_raw 实时算.

复用 stock_meta_repo 的阈值/is_st 推断. 输出 dict 形状与
limit_emotion_service.snapshot_today_daily 的字段兼容.

算法:
  - 用 LAG(close) 取 pre_close, 算涨停价 limit_up_price = pre_close * (1 + threshold)
  - close >= limit_up_price * (1 - tol) → is_limit_up (封板)
  - high  >= limit_up_price * (1 - tol) → is_touched  (盘中触板)
  - 连板 streak: ROW_NUMBER 减去前一个非涨停日 ROW_NUMBER 的累加计数
"""
from __future__ import annotations

from datetime import date
from typing import Any

from backend.adapters.market.duckdb_store import get_conn
from backend.repositories.market.stock_meta_repo import (
    get_threshold,
    is_st_by_name,
    list_universe,
)

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
                 LAG(r.close) OVER w_ AS pre_close
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
                         LAG(is_limit_up) OVER (PARTITION BY code ORDER BY trade_date) = 1
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

    性能: 5500 只 × 60 天 × LAG = 单次 DuckDB 扫 ≈ 几十万行, < 1s.
    """
    con = get_conn()
    placeholders = ",".join(["?"] * len(codes))

    # 今天 OHLC + pre_close.
    # 用 LATERAL join (subquery) 拿最近的 "td 之前" 的最近一个交易日的 close
    # 而不是 LAG OVER (PARTITION BY code) — 后者在今天=该 code 第一天时返回 NULL.
    today_rows = con.execute(f"""
        WITH today AS (
          SELECT code, trade_date, open, high, low, close, volume
            FROM daily_raw
           WHERE code IN ({placeholders}) AND trade_date = ?
        )
        SELECT t.code, t.open, t.high, t.low, t.close, t.volume,
               (SELECT close FROM daily_raw p
                 WHERE p.code = t.code AND p.trade_date < t.trade_date
                 ORDER BY p.trade_date DESC LIMIT 1) AS pre_close
          FROM today t
    """, [*codes, td]).fetchall()
    today_by_code = {r[0]: r for r in today_rows}
    if not today_by_code:
        return []

    # 限定到最近 90 天, 避免扫全历史 (28M 行). 60 个交易日足够覆盖绝大多数连板.
    from datetime import timedelta
    history_start = td - timedelta(days=120)
    raw_history = con.execute(f"""
        SELECT code, trade_date, close,
               (SELECT close FROM daily_raw p
                 WHERE p.code = code AND p.trade_date < trade_date
                 ORDER BY p.trade_date DESC LIMIT 1) AS pre_close
          FROM daily_raw
         WHERE code IN ({placeholders}) AND trade_date >= ? AND trade_date < ?
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
        is_limit_up = close_p >= limit_up_price * (1 - _TOL)
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
            "changePct": round((close_p - pre_close) / pre_close * 100, 2),
            "isLimitUp": is_limit_up,
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
# smoke
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json as _json
    print("=== 单股连板历史 (000001, 最近 60 天) ===")
    hist = get_limit_streak_history("000001", end="2026-06-16")
    for row in hist[-10:]:
        print(_json.dumps(row, ensure_ascii=False))
    print()
    print("=== 单日快照 (2026-06-15) 前 10 名 ===")
    snap = get_today_limit_snapshot("2026-06-15")
    for row in snap[:10]:
        print(_json.dumps(row, ensure_ascii=False))
    print(f"total: {len(snap)}")
    print()
    print("=== 连板分布 (2026-06-15) ===")
    dist = get_limit_streak_distribution("2026-06-15")
    print(f"maxHeight={dist['maxHeight']}, leaders={len(dist['leaders'])}, "
          f"distribution={[d['streak'] for d in dist['distribution']]}")
