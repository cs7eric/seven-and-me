"""Batch 回填 profit_effect_daily (3 年).

数据源: ma_count_daily (up_5d_pct, new_low_60d_pct)
公式:   score = 0.60 × up_5d_pct + 0.40 × (100 - new_low_60d_pct)
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
log = logging.getLogger("backfill_profit_effect_batch")

_BATCH_SQL = """
SELECT
  trade_date,
  up_5d_pct,
  new_low_60d_pct,
  0.60 * up_5d_pct + 0.40 * (100.0 - new_low_60d_pct) AS score
FROM ma_count_daily
WHERE trade_date BETWEEN ? AND ?
ORDER BY trade_date
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1100, help="回填窗口天数")
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

    log.info("Step 1/2: 单条 SQL JOIN ma_count_daily 算 score ...")
    rows = con.execute(_BATCH_SQL, [start_d, end_d]).fetchall()
    log.info("  算出 %d 行 (%.1fs)", len(rows), time.time() - t0)

    existing_dates: set[date] = set()
    if not args.full:
        r = con.execute(
            "SELECT trade_date FROM profit_effect_daily "
            "WHERE trade_date >= ? AND trade_date <= ?",
            [start_d, end_d],
        ).fetchall()
        existing_dates = {row[0] for row in r}
        log.info("  已有 %d 天 (skip)", len(existing_dates))

    payload = []
    for r in rows:
        td, up5d, new_low60d, score = r
        if not args.full and td in existing_dates:
            continue
        if up5d is None or new_low60d is None:
            continue
        payload.append((
            td,
            round(float(up5d), 2),
            round(float(new_low60d), 2),
            round(float(score), 2),
            int((time.time() - t0) * 1000),
            "batch.sql.ma_count",
        ))

    log.info("  待 INSERT: %d 行", len(payload))
    if not payload:
        return 0

    log.info("Step 2/2: 批量 INSERT ...")
    con.executemany("""
        INSERT OR REPLACE INTO profit_effect_daily
            (trade_date, up_5d_pct, new_low_60d_pct, score,
             elapsed_ms, source, ingested_at)
        VALUES (?, ?, ?, ?,
                ?, ?, current_timestamp)
    """, payload)
    log.info("  INSERT 完成 (%.1fs)", time.time() - t0)

    r = con.execute(
        "SELECT COUNT(*), MIN(trade_date), MAX(trade_date) FROM profit_effect_daily"
    ).fetchone()
    log.info("最终: rows=%d  range=%s -> %s", r[0], r[1], r[2])
    log.info("总耗时 %.1fs", time.time() - t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())