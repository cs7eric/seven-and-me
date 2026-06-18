"""Batch 回填 volatility_sentiment_daily (单条 SQL, 3 年).

数据源: index_daily_raw[sh000300] (沪深300 K 线).
公式: vol[t] = std(ret[t-20..t-1]) * sqrt(252) * 100
      percentile_1y = count(vol <= current_vol) / count(vol)  (样本 = 过去 252 天, 不含今天)
      sentiment_score = 100 - percentile_1y * 100  (反向: 波动率低 = 情绪好)
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
log = logging.getLogger("backfill_vol_sentiment_batch")

VOL_WINDOW = 20
VOL_LOOKBACK = 252
UNDERLYING_CODE = "sh000300"
UNDERLYING_NAME = "沪深300"

# Lookback 252 trading days ≈ 380 calendar days; 加 buffer 到 500
_CAL_LOOKBACK_DAYS = 500

_BATCH_SQL = f"""
WITH idx AS (
  SELECT trade_date, close
    FROM index_daily_raw
   WHERE code = ? AND trade_date BETWEEN ? AND ?
),
with_ret AS (
  SELECT trade_date, close,
    CASE WHEN LAG(close) OVER (ORDER BY trade_date) IS NULL
              OR LAG(close) OVER (ORDER BY trade_date) = 0
         THEN NULL
         ELSE (close - LAG(close) OVER (ORDER BY trade_date))
            / LAG(close) OVER (ORDER BY trade_date)
    END AS ret
  FROM idx
),
with_vol AS (
  SELECT trade_date, close, ret,
    STDDEV(ret) OVER (ORDER BY trade_date ROWS BETWEEN {VOL_WINDOW} PRECEDING AND 1 PRECEDING)
        * SQRT(252) * 100 AS vol_20d,
    COUNT(ret) OVER (ORDER BY trade_date ROWS BETWEEN {VOL_WINDOW} PRECEDING AND 1 PRECEDING) AS n_in_vol
  FROM with_ret
)
SELECT
  trade_date,
  close,
  ret * 100 AS daily_return_pct,
  vol_20d AS realized_vol_20d,
  {VOL_WINDOW} AS vol_window_days,
  {VOL_LOOKBACK} AS vol_lookback_days,
  n_in_vol,
  -- 历史样本 = 过去 ~500 天的 vol (实际最多 252 trading days)
  (SELECT COUNT(*) FROM with_vol v2
    WHERE v2.trade_date < v1.trade_date
      AND v2.trade_date >= v1.trade_date - INTERVAL '{_CAL_LOOKBACK_DAYS} days'
      AND v2.vol_20d IS NOT NULL
      AND v2.vol_20d <= v1.vol_20d) AS n_le,
  (SELECT COUNT(*) FROM with_vol v2
    WHERE v2.trade_date < v1.trade_date
      AND v2.trade_date >= v1.trade_date - INTERVAL '{_CAL_LOOKBACK_DAYS} days'
      AND v2.vol_20d IS NOT NULL) AS sample_count
FROM with_vol v1
ORDER BY trade_date
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1100, help="回填窗口天数 (默认 1100 ≈ 3 年)")
    ap.add_argument("--start", type=str, default=None)
    ap.add_argument("--end", type=str, default=None)
    ap.add_argument("--full", action="store_true", help="覆盖已有记录")
    args = ap.parse_args()

    today = date.today()
    end_d = date.fromisoformat(args.end) if args.end else today
    start_d = (
        date.fromisoformat(args.start) if args.start else end_d - timedelta(days=args.days)
    )
    log.info("回填窗口: %s ~ %s (full=%s)", start_d, end_d, args.full)

    con = get_conn()
    t0 = time.time()

    log.info("Step 1/2: 单条 SQL 算完所有天的 vol + percentile + sentiment_score ...")
    rows = con.execute(_BATCH_SQL, [UNDERLYING_CODE, start_d, end_d]).fetchall()
    log.info("  算出 %d 行 (%.1fs)", len(rows), time.time() - t0)

    # 默认只补缺失的; --full 才覆盖
    existing_dates: set[date] = set()
    if not args.full:
        r = con.execute(
            "SELECT trade_date FROM volatility_sentiment_daily "
            "WHERE trade_date >= ? AND trade_date <= ?",
            [start_d, end_d],
        ).fetchall()
        existing_dates = {row[0] for row in r}
        log.info("  已有 %d 天 (skip)", len(existing_dates))

    payload_rows = []
    for r in rows:
        td, close, daily_ret, vol_20d, win_days, lookback_days, n_in_vol, n_le, sample_count = r

        if not args.full and td in existing_dates:
            continue
        if vol_20d is None or n_in_vol < VOL_WINDOW or sample_count == 0:
            continue

        percentile = round(n_le / sample_count, 4)
        sentiment_score = round((1.0 - percentile) * 100.0, 2)
        payload_rows.append((
            td, UNDERLYING_CODE, UNDERLYING_NAME, close,
            round(daily_ret, 4) if daily_ret is not None else None,
            round(vol_20d, 2),
            win_days, lookback_days,
            percentile, sentiment_score,
            sample_count,
            int((time.time() - t0) * 1000),
            "batch.sql.window",
        ))

    log.info("  待 INSERT: %d 行", len(payload_rows))
    if not payload_rows:
        log.info("没有可写入的行")
        return 0

    log.info("Step 2/2: 批量 INSERT ...")
    con.executemany("""
        INSERT OR REPLACE INTO volatility_sentiment_daily
            (trade_date, underlying_code, underlying_name, close, daily_return_pct,
             realized_vol_20d, vol_window_days, vol_lookback_days,
             percentile_1y, sentiment_score, sample_count,
             elapsed_ms, source, ingested_at)
        VALUES (?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, current_timestamp)
    """, payload_rows)
    log.info("  INSERT 完成 (%.1fs)", time.time() - t0)

    # 校验
    r = con.execute(
        "SELECT COUNT(*), MIN(trade_date), MAX(trade_date) FROM volatility_sentiment_daily"
    ).fetchone()
    log.info("最终: rows=%d  range=%s -> %s", r[0], r[1], r[2])
    log.info("总耗时 %.1fs", time.time() - t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())