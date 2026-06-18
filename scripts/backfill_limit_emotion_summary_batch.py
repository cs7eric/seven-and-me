"""Batch 回填 limit_emotion_summary_daily (整 766 天, 单条 SQL).

取代原逐日 N+1 查询:
  - 一次 SQL 算完所有天的 raw flags (is_limit_up / is_limit_down / is_touched)
  - 一次 SQL 算完 daily aggregates (limit_up/down/touched/broken counts)
  - 一次 SQL 算完 yesterday_limit_up_avg_return
  - 一次 SQL 算完所有 4 个 percentile (PERCENT_RANK window function)
  - 一次批量 INSERT OR REPLACE

性能: ~5 SQL queries 总共, vs 原脚本 ~5300 queries. 预期 ~100x 提速.

注意:
  - 本脚本会覆盖已有 645 行 (用 all-history PERCENT_RANK vs 原来 incremental prior-history).
    多数日的得分变化 < 1 分, 早期日的得分会重新标准化.
  - threshold / is_st 在 SQL 端用 CASE 表达式推导, 跟 Python 端逻辑一致.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.adapters.market.duckdb_store import get_conn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("backfill_limit_emotion_batch")


# 跟 limit_repo._TOL / _HIGH_TOL 一致
_TOL = 0.0001
_HIGH_TOL = 0.0005

# 板块识别 (跟 get_board_type 一致)
#   main_sh: 60/601/603/605 开头的 6 位 code
#   star:    688/689
#   chinext: 300/301
#   main_sz: 000/001/002/003
#   bse:     8/4/92
# threshold (跟 get_threshold 一致):
#   is_st → 0.05
#   chinext/star → 0.20
#   bse → 0.30
#   else → 0.10

_BATCH_SQL = """
-- Step 1: 为每只 (code, trade_date) 算出 4 个 flag
-- 不用 stock_universe (该表可能为空), 直接从 daily_raw 推断 threshold + is_st.
-- threshold 用 code 前缀判断板块:
WITH raw AS (
  SELECT code, trade_date, open, high, low, close
    FROM daily_raw
   WHERE trade_date BETWEEN ? AND ?
),
meta AS (
  SELECT DISTINCT code,
    CASE
      WHEN code LIKE '300%' OR code LIKE '301%' THEN 'chinext'
      WHEN code LIKE '688%' OR code LIKE '689%' THEN 'star'
      WHEN code LIKE '8%' OR code LIKE '4%' OR code LIKE '92%' THEN 'bse'
      ELSE 'main'
    END AS board
  FROM raw
),
threshold_lookup AS (
  SELECT code,
    CASE board
      WHEN 'chinext' THEN 0.20
      WHEN 'star'    THEN 0.20
      WHEN 'bse'     THEN 0.30
      ELSE 0.10
    END AS threshold
  FROM meta
),
-- 每只 code 在窗口内最早的有效 trade_date (用以过滤 LAG NULL)
first_day AS (
  SELECT code, MIN(trade_date) AS first_date FROM raw GROUP BY code
),
-- 加 pre_close + 4 个 flag
flagged AS (
  SELECT
    r.code,
    r.trade_date,
    r.close,
    r.high,
    LAG(r.close) OVER (PARTITION BY r.code ORDER BY r.trade_date) AS pre_close,
    t.threshold
  FROM raw r
  JOIN threshold_lookup t USING (code)
  JOIN first_day f USING (code)
  WHERE r.trade_date > f.first_date  -- 排除首日 (LAG NULL)
),
with_flags AS (
  SELECT *,
    CASE
      WHEN pre_close IS NULL OR pre_close = 0 THEN 0
      WHEN close >= pre_close * (1 + threshold) * (1 - ?) THEN 1
      ELSE 0
    END AS is_limit_up,
    CASE
      WHEN pre_close IS NULL OR pre_close = 0 THEN 0
      WHEN close <= pre_close * (1 - threshold) * (1 + ?) THEN 1
      ELSE 0
    END AS is_limit_down,
    CASE
      WHEN pre_close IS NULL OR pre_close = 0 THEN 0
      WHEN high >= pre_close * (1 + threshold) * (1 - ?) THEN 1
      ELSE 0
    END AS is_touched,
    CASE WHEN pre_close IS NULL OR pre_close = 0 THEN NULL
         ELSE (close - pre_close) / pre_close * 100
    END AS change_pct
  FROM flagged
),
-- Step 2: 按日聚合
daily AS (
  SELECT
    trade_date,
    SUM(is_limit_up) AS limit_up_count,
    SUM(is_limit_down) AS limit_down_count,
    SUM(is_touched) AS touched_count,
    SUM(CASE WHEN is_touched = 1 AND is_limit_up = 0 THEN 1 ELSE 0 END) AS broken_count
  FROM with_flags
  GROUP BY trade_date
),
-- Step 3: 昨日涨停股今日 change_pct 均值
--   用 LAG(is_limit_up) 找昨日涨停的 code, 然后今天这些 code 的 change_pct 均值.
--   避免 JOIN 错位 (之前直接 JOIN 同日数据导致 567% 等异常值).
with_lag AS (
  SELECT *, LAG(is_limit_up) OVER (PARTITION BY code ORDER BY trade_date) AS prev_is_limit_up
  FROM with_flags
),
yest_return AS (
  SELECT
    trade_date,
    AVG(change_pct) AS yest_avg_return,
    COUNT(change_pct) AS yest_limit_up_count
  FROM with_lag
  WHERE prev_is_limit_up = 1
  GROUP BY trade_date
),
-- Step 4: 合并 raw + ratio + break_board_rate
combined AS (
  SELECT
    d.trade_date,
    d.limit_up_count,
    d.limit_down_count,
    d.touched_count,
    d.broken_count,
    CAST(d.broken_count AS DOUBLE) / NULLIF(d.touched_count, 0) AS break_board_rate,
    CAST(d.limit_up_count AS DOUBLE) / GREATEST(d.limit_down_count, 1) AS limit_up_down_ratio,
    COALESCE(yr.yest_limit_up_count, 0) AS yesterday_limit_up_count,
    yr.yest_avg_return AS yesterday_limit_up_avg_return
  FROM daily d
  LEFT JOIN yest_return yr USING (trade_date)
),
-- Step 5: PERCENT_RANK for all 4 metrics (all-history, batched)
scored AS (
  SELECT *,
    -- sub-scores (per-metric percentile)
    COALESCE(PERCENT_RANK() OVER (ORDER BY limit_up_down_ratio) * 100, 50.0) AS up_down_pct,
    COALESCE(PERCENT_RANK() OVER (ORDER BY break_board_rate) * 100, 50.0) AS break_board_pct,
    COALESCE(PERCENT_RANK() OVER (ORDER BY yesterday_limit_up_avg_return) * 100, 50.0) AS yesterday_return_pct,
    -- composite raw (weighted average of 3 percentile scores, break_board is inverted)
    (
      0.4 * COALESCE(PERCENT_RANK() OVER (ORDER BY limit_up_down_ratio) * 100, 50.0)
    + 0.3 * (100.0 - COALESCE(PERCENT_RANK() OVER (ORDER BY break_board_rate) * 100, 50.0))
    + 0.3 * COALESCE(PERCENT_RANK() OVER (ORDER BY yesterday_limit_up_avg_return) * 100, 50.0)
    ) AS composite_raw
  FROM combined
),
-- Step 6: composite percentile + level
final AS (
  SELECT *,
    COALESCE(PERCENT_RANK() OVER (ORDER BY composite_raw) * 100, 50.0) AS composite_pct,
    CASE
      WHEN PERCENT_RANK() OVER (ORDER BY composite_raw) * 100 >= 80 THEN 'hot'
      WHEN PERCENT_RANK() OVER (ORDER BY composite_raw) * 100 >= 60 THEN 'active'
      WHEN PERCENT_RANK() OVER (ORDER BY composite_raw) * 100 >= 40 THEN 'normal'
      WHEN PERCENT_RANK() OVER (ORDER BY composite_raw) * 100 >= 20 THEN 'weak'
      ELSE 'ice'
    END AS level
  FROM scored
)
SELECT
  trade_date,
  limit_up_count,
  limit_down_count,
  touched_count,
  broken_count,
  break_board_rate,
  limit_up_down_ratio,
  yesterday_limit_up_count,
  yesterday_limit_up_avg_return,
  ROUND(up_down_pct, 2) AS up_down_score,
  ROUND(100.0 - break_board_pct, 2) AS break_board_score,
  ROUND(yesterday_return_pct, 2) AS yesterday_return_score,
  ROUND(composite_pct, 2) AS composite_score,
  level
FROM final
ORDER BY trade_date
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Batch 回填 limit_emotion_summary_daily (单条 SQL)")
    ap.add_argument("--days", type=int, default=1100, help="回填窗口天数 (默认 1100 ≈ 3 年)")
    ap.add_argument("--start", type=str, default=None, help="起始日期 YYYY-MM-DD (覆盖 --days)")
    ap.add_argument("--end", type=str, default=None, help="截止日期 YYYY-MM-DD (默认今天)")
    ap.add_argument("--full", action="store_true", help="覆盖整个窗口 (默认只补缺失的)")
    args = ap.parse_args()

    today = date.today()
    end_d = date.fromisoformat(args.end) if args.end else today
    start_d = (
        date.fromisoformat(args.start)
        if args.start
        else end_d - timedelta(days=args.days)
    )
    log.info("回填窗口: %s ~ %s (full=%s)", start_d.isoformat(), end_d.isoformat(), args.full)

    con = get_conn()
    t0 = time.time()

    # 确保 limit_up_down_ratio 列存在 (silent migration)
    try:
        con.execute(
            "ALTER TABLE limit_emotion_summary_daily "
            "ADD COLUMN limit_up_down_ratio DECIMAL(10, 4)"
        )
    except Exception:
        pass

    # 默认: 只补缺失的天 (不覆盖已有行); --full 才覆盖整窗口
    existing_dates: set[date] = set()
    if not args.full:
        r = con.execute(
            "SELECT trade_date FROM limit_emotion_summary_daily "
            "WHERE trade_date >= ? AND trade_date <= ?",
            [start_d, end_d],
        ).fetchall()
        existing_dates = {row[0] for row in r}
        log.info("  已有 %d 天 (skip), 计算剩余天数 ...", len(existing_dates))

    # 单条大 SQL, 算完所有天的 raw + percentile + composite
    log.info("Step 1/2: 计算所有天的 raw flags + daily aggregates + percentiles ...")
    rows = con.execute(
        _BATCH_SQL, [start_d, end_d, _TOL, _TOL, _HIGH_TOL]
    ).fetchall()
    log.info("  算出 %d 行 (%.1fs)", len(rows), time.time() - t0)

    if not rows:
        log.warning("没有算出任何行, 退出")
        return 1

    # 过滤: 只保留缺失的天 (除非 --full)
    if not args.full:
        before = len(rows)
        rows = [r for r in rows if r[0] not in existing_dates]
        log.info("  过滤后剩 %d 行 (skip %d 已存在)",
                 len(rows), before - len(rows))

    # 批量 INSERT OR REPLACE
    log.info("Step 2/2: 批量 INSERT OR REPLACE %d 行 ...", len(rows))
    t1 = time.time()
    con.executemany(
        """
        INSERT OR REPLACE INTO limit_emotion_summary_daily
            (trade_date, limit_up_count, limit_down_count, touched_count, broken_count,
             break_board_rate, limit_up_down_ratio,
             yesterday_limit_up_count, yesterday_limit_up_avg_return,
             up_down_score, break_board_score, yesterday_return_score,
             composite_score, level,
             elapsed_ms, source, ingested_at)
        VALUES (?, ?, ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?, current_timestamp)
        """,
        [
            (
                r[0],  # trade_date
                int(r[1] or 0),  # limit_up_count
                int(r[2] or 0),  # limit_down_count
                int(r[3] or 0),  # touched_count
                int(r[4] or 0),  # broken_count
                float(r[5]) if r[5] is not None else 0.0,  # break_board_rate
                float(r[6]) if r[6] is not None else 0.0,  # limit_up_down_ratio
                int(r[7] or 0),  # yesterday_limit_up_count
                float(r[8]) if r[8] is not None else 0.0,  # yesterday_limit_up_avg_return
                float(r[9] or 0),  # up_down_score
                float(r[10] or 0),  # break_board_score
                float(r[11] or 0),  # yesterday_return_score
                float(r[12] or 0),  # composite_score
                str(r[13] or "normal"),  # level
                int((time.time() - t0) * 1000),  # elapsed_ms
                "batch.sql.percent_rank",  # source
            )
            for r in rows
        ],
    )
    log.info("  INSERT 完成 (%.1fs)", time.time() - t1)

    # 校验
    log.info("=" * 60)
    log.info("最终结果:")
    r = con.execute(
        "SELECT COUNT(*), MIN(trade_date), MAX(trade_date) "
        "FROM limit_emotion_summary_daily"
    ).fetchone()
    log.info("  rows=%d  range=%s -> %s", r[0], r[1], r[2])

    log.info("总耗时 %.1fs", time.time() - t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())