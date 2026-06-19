"""成交活跃度 duckdb 回填脚本.

计算公式: ratio = 当日全市场成交额 / 过去 20 日平均成交额
数据源: duckdb.market_overview_daily.total_amount
目标表: turnover_activity_daily (INSERT OR REPLACE by trade_date)

幂等: 全部走 INSERT OR REPLACE, 重复跑不写脏.

用法:
    python scripts/backfill_turnover_activity.py
    python scripts/backfill_turnover_activity.py --days=60
    python scripts/backfill_turnover_activity.py --start=2026-06-01 --end=2026-06-17
    python scripts/backfill_turnover_activity.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("backfill_turnover_activity")

from backend.adapters.market.duckdb_store import init_schema


def main() -> int:
    ap = argparse.ArgumentParser(description="成交活跃度 duckdb 回填")
    ap.add_argument("--days", type=int, default=60, help="回填最近 N 天 (默认 60)")
    ap.add_argument("--start", type=str, default=None, help="起始日 YYYY-MM-DD")
    ap.add_argument("--end", type=str, default=None, help="结束日 YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划, 不执行")
    args = ap.parse_args()

    init_schema()

    from backend.adapters.market.duckdb_store import conn
    from backend.repositories.market.turnover_activity_repo import (
        calc_turnover_activity,
        save_turnover_activity,
        _add_score,
    )

    with conn() as c:
        # 取 market_overview_daily 的日期范围 (有 total_amount 的)
        row = c.execute("""
            SELECT MIN(trade_date), MAX(trade_date)
              FROM market_overview_daily
             WHERE total_amount IS NOT NULL
        """).fetchone()
        if not row or row[0] is None:
            log.warning("market_overview_daily 无数据, 请先跑 backfill_market_overview_daily")
            return 1
        db_min, db_max = row[0], row[1]
        db_min = db_min.date() if hasattr(db_min, "date") else db_min
        db_max = db_max.date() if hasattr(db_max, "date") else db_max

    today = date.today()
    if args.start:
        start = date.fromisoformat(args.start)
    else:
        start = max(db_min, today - timedelta(days=args.days))
    if args.end:
        end = date.fromisoformat(args.end)
    else:
        end = min(db_max, today)

    if start > end:
        log.warning("start=%s > end=%s, 无数据可回填", start, end)
        return 0

    # 取所有 trade_dates (从 market_overview_daily, 有 total_amount 的)
    with conn() as c:
        rows = c.execute(
            "SELECT DISTINCT trade_date FROM market_overview_daily "
            "WHERE trade_date BETWEEN ? AND ? AND total_amount IS NOT NULL "
            "ORDER BY trade_date",
            [start, end],
        ).fetchall()
    trade_dates = [
        r[0].date() if hasattr(r[0], "date") else r[0]
        for r in rows
    ]
    log.info("market_overview_daily 在 %s ~ %s 中共 %d 个交易日 (有 total_amount)", start, end, len(trade_dates))
    if args.dry_run:
        log.info("[dry-run] 不会执行写入")
        return 0

    ok_count = 0
    fail_count = 0
    t0 = time.time()
    for td in trade_dates:
        try:
            payload = calc_turnover_activity(td)
            if payload is None:
                log.debug("  %s 数据不足, 跳过", td)
                continue
            _add_score(payload, td)
            save_turnover_activity(payload)
            ok_count += 1
        except Exception as exc:
            log.warning("  %s failed: %s", td, exc)
            fail_count += 1
        if ok_count % 20 == 0:
            log.info("  processed %d/%d...", ok_count + fail_count, len(trade_dates))

    elapsed = time.time() - t0
    log.info("done: ok=%d fail=%d in %.1fs", ok_count, fail_count, elapsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
