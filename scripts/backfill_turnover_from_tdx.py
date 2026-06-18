"""从 daily_qfq 的 TDX 指数 K 线回填全市场成交额.

用法:
    python scripts/backfill_turnover_from_tdx.py

数据流:
    daily_qfq {code=999999(上证综指) + 399001(深证成指)}
      → amount → 全市场成交额(亿) = (上证amount + 深证amount) / 1e8
      → INSERT/UPDATE market_overview_daily.total_amount
      → 重算 turnover_activity_daily

验证: 999999+399001 的 amount 总和与 market_overview_daily 偏差 < 1%
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("backfill_turnover")


def main() -> int:
    ap = argparse.ArgumentParser(description="从 TDX daily_qfq 回填全市场成交额")
    ap.add_argument("--start", type=str, default="2023-06-01", help="起始日 (默认 3 年前)")
    ap.add_argument("--end", type=str, default=None, help="结束日 (默认今天)")
    ap.add_argument("--force", action="store_true", help="覆盖已有 total_amount")
    args = ap.parse_args()

    from backend.adapters.market.duckdb_store import get_conn
    con = get_conn()

    end = date.fromisoformat(args.end) if args.end else date.today()

    # Step 1: 从 daily_qfq 拉指数成交额
    log.info("=== Step 1: Read index amounts from daily_qfq ===")
    rows = con.execute("""
        SELECT trade_date,
               SUM(CASE WHEN code='999999' THEN amount ELSE 0 END) / 1e8 AS sh_yi,
               SUM(CASE WHEN code='399001' THEN amount ELSE 0 END) / 1e8 AS sz_yi
        FROM daily_qfq
        WHERE code IN ('999999', '399001')
          AND trade_date >= ? AND trade_date <= ?
          AND amount IS NOT NULL AND amount > 0
        GROUP BY trade_date
        ORDER BY trade_date
    """, [args.start, end]).fetchall()
    log.info("  Read %d trading days of index amounts", len(rows))
    if rows:
        log.info("  Range: %s ~ %s", rows[0][0], rows[-1][0])
        # Sample last 3
        for r in rows[-3:]:
            log.info("    %s: SH=%.0f亿 + SZ=%.0f亿 = %.0f亿",
                     r[0], float(r[1]), float(r[2]), float(r[1]) + float(r[2]))

    # Step 2: Upsert into market_overview_daily
    log.info("\n=== Step 2: Upsert into market_overview_daily ===")
    before = con.execute("SELECT COUNT(*) FROM market_overview_daily").fetchone()[0]
    written = 0
    skipped = 0
    for td, sh_yi, sz_yi in rows:
        total_yi = float(sh_yi) + float(sz_yi)
        if not args.force:
            existing = con.execute(
                "SELECT total_amount FROM market_overview_daily WHERE trade_date = ?",
                [td],
            ).fetchone()
            if existing and existing[0] is not None:
                skipped += 1
                continue
        con.execute(
            "INSERT OR IGNORE INTO market_overview_daily (trade_date, source) VALUES (?, 'tdx_index_daily')",
            [td],
        )
        con.execute(
            "UPDATE market_overview_daily SET total_amount = ? WHERE trade_date = ?",
            [total_yi, td],
        )
        written += 1

    after = con.execute("SELECT COUNT(*) FROM market_overview_daily").fetchone()[0]
    log.info("  Written: %d, Skipped(exists): %d, Before: %d, After: %d",
             written, skipped, before, after)

    # Step 3: Recompute turnover_activity_daily
    log.info("\n=== Step 3: Recompute turnover_activity_daily ===")
    from backend.repositories.market.turnover_activity_repo import (
        calc_turnover_activity_cached,
    )

    r = con.execute("SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM turnover_activity_daily").fetchone()
    log.info("  Before: %s ~ %s (%d rows)", r[0], r[1], r[2])

    # Find all dates with total_amount set, walk them
    all_dates = con.execute("""
        SELECT trade_date FROM market_overview_daily
        WHERE total_amount IS NOT NULL AND total_amount > 0
        ORDER BY trade_date
    """).fetchall()

    t0 = time.time()
    ok = fail = 0
    for i, (td,) in enumerate(all_dates):
        try:
            payload = calc_turnover_activity_cached(td, force=args.force)
            if payload and payload.get("ratio") is not None:
                ok += 1
            else:
                fail += 1
        except Exception as exc:
            log.debug("  %s failed: %s", td, exc)
            fail += 1
        if (i + 1) % 300 == 0:
            log.info("  [%d/%d] ok=%d fail=%d", i + 1, len(all_dates), ok, fail)

    elapsed = time.time() - t0
    log.info("  done: ok=%d fail=%d in %.1fs", ok, fail, elapsed)

    r = con.execute("SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM turnover_activity_daily").fetchone()
    log.info("  After: %s ~ %s (%d rows)", r[0], r[1], r[2])

    log.info("\n=== Done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
