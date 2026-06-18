"""风格风险偏好 duckdb 回填脚本.

核心指标:
  spread = 中证1000 近 5 日收益率 - 沪深300 近 5 日收益率

数据源: duckdb.index_returns_daily (已由 ma_count_scheduler 每日 17:06 更新)
目标表: style_risk_appetite_daily (INSERT OR REPLACE by trade_date)

幂等: 全部走 INSERT OR REPLACE, 重复跑不写脏.

用法:
    python scripts/backfill_style_risk_appetite.py
    python scripts/backfill_style_risk_appetite.py --days=60
    python scripts/backfill_style_risk_appetite.py --start=2026-06-01 --end=2026-06-17
    python scripts/backfill_style_risk_appetite.py --dry-run
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
log = logging.getLogger("backfill_style_risk_appetite")

from backend.adapters.market.duckdb_store import init_schema


def main() -> int:
    ap = argparse.ArgumentParser(description="风格风险偏好 duckdb 回填")
    ap.add_argument("--days", type=int, default=60, help="回填最近 N 天 (默认 60)")
    ap.add_argument("--start", type=str, default=None, help="起始日 YYYY-MM-DD")
    ap.add_argument("--end", type=str, default=None, help="结束日 YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划, 不执行")
    ap.add_argument("--force", action="store_true", help="跳过 cache 强制重算")
    args = ap.parse_args()

    init_schema()

    from backend.adapters.market.duckdb_store import conn
    from backend.repositories.market.style_risk_appetite_repo import (
        calc_style_risk_appetite,
        save_style_risk_appetite,
    )

    with conn() as c:
        row = c.execute("""
            SELECT MIN(trade_date), MAX(trade_date)
              FROM index_returns_daily
             WHERE index_code = 'sh000300' AND window_days = 5
        """).fetchone()
        if not row or row[0] is None:
            log.warning("index_returns_daily 无数据, 请先跑 backfill_ma_count_and_returns.py")
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

    with conn() as c:
        rows = c.execute(
            "SELECT DISTINCT trade_date FROM index_returns_daily "
            "WHERE trade_date BETWEEN ? AND ? AND index_code = 'sh000300' AND window_days = 5 "
            "ORDER BY trade_date",
            [start, end],
        ).fetchall()
    trade_dates = [
        r[0].date() if hasattr(r[0], "date") else r[0]
        for r in rows
    ]
    log.info("index_returns_daily 在 %s ~ %s 中共 %d 个交易日", start, end, len(trade_dates))
    if args.dry_run:
        log.info("[dry-run] 不会执行写入")
        return 0

    ok_count = 0
    fail_count = 0
    t0 = time.time()
    for td in trade_dates:
        try:
            payload = calc_style_risk_appetite(td)
            if payload is None:
                log.debug("  %s 数据不足, 跳过", td)
                continue
            if args.force:
                save_style_risk_appetite(payload)
            else:
                from backend.repositories.market.style_risk_appetite_repo import (
                    calc_style_risk_appetite_cached,
                )
                calc_style_risk_appetite_cached(td, force=True)
            ok_count += 1
        except Exception as exc:
            log.warning("  %s failed: %s", td, exc)
            fail_count += 1

    elapsed = time.time() - t0
    log.info("done: ok=%d fail=%d in %.1fs", ok_count, fail_count, elapsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
