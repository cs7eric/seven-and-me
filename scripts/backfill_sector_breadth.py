"""板块扩散 → market_pulse_sector_breadth_daily 回填.

数据源 (扫 duckdb, 不走网络):
  ths_industry_fund_flow_daily (§18) — 取所有 DISTINCT trade_date,
  对每个日期聚合算 advancing/declining/flat/total/advance_pct,
  upsert 到 market_pulse_sector_breadth_daily (§19).

幂等: 全部走 INSERT OR REPLACE by trade_date, 重复跑不写脏.

用法:
    python scripts/backfill_sector_breadth.py
    python scripts/backfill_sector_breadth.py --days=365
    python scripts/backfill_sector_breadth.py --date=2026-06-16   # 单日
    python scripts/backfill_sector_breadth.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("backfill_sector_breadth")


def main() -> int:
    ap = argparse.ArgumentParser(description="回填板块扩散到 duckdb")
    ap.add_argument("--days", type=int, default=365,
                    help="回填最近 N 天 (默认 365)")
    ap.add_argument("--date", type=str, default=None,
                    help="单日 YYYY-MM-DD, 只回填这一天")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    log.info("start: days=%s date=%s dry_run=%s",
             args.days, args.date, args.dry_run)

    # 初始化 schema (幂等)
    from backend.adapters.market.duckdb_store import init_schema
    init_schema()
    log.info("schema 初始化完成 (幂等)")

    from backend.repositories.market.sector_breadth_repo import (
        upsert_sector_breadth, coverage, get_sector_breadth_history,
    )

    # 单日模式
    if args.date:
        n = upsert_sector_breadth(args.date)
        log.info("upserted %d 行 (date=%s)", n, args.date)
        return 0 if n > 0 or args.dry_run else 1

    # 区间模式: 扫 ths_industry_fund_flow_daily 所有 DISTINCT trade_date
    # 重要: 用 conn() contextmanager (不是 with get_conn()), 避免 DuckDBPyConnection.__exit__ close
    from backend.adapters.market.duckdb_store import conn
    cutoff = date.today() - timedelta(days=args.days)
    with conn() as c:
        date_rows = c.execute(
            "SELECT DISTINCT trade_date FROM ths_industry_fund_flow_daily "
            "WHERE trade_date >= ? ORDER BY trade_date ASC",
            [cutoff],
        ).fetchall()
    dates = [r[0] for r in date_rows]
    log.info("ths_industry_fund_flow_daily 命中 %d 天 (>= %s)", len(dates), cutoff)

    if args.dry_run:
        log.info("[dry-run] 没写任何东西")
        return 0

    n_ok = 0
    n_skip = 0
    for td in dates:
        try:
            n = upsert_sector_breadth(td)
            if n > 0:
                n_ok += 1
            else:
                n_skip += 1
        except Exception as exc:
            log.warning("upsert %s failed: %s", td, exc)
    log.info("done.  upserted=%d skipped=%d total=%d", n_ok, n_skip, len(dates))
    log.info("coverage: %s", coverage())

    # 跨日趋势 dump
    history = get_sector_breadth_history(
        start=cutoff.isoformat(),
        end=date.today().isoformat(),
        limit=10,
    )
    log.info("--- 近 10 天 advance_pct 序列 ---")
    for h in history[-10:]:
        log.info("  %s  adv=%2d/%2d  dec=%2d  flat=%2d  adv_pct=%.2f%%",
                 h["tradeDate"], h["advancing"], h["total"],
                 h["declining"], h["flat"], h["advancePct"] * 100)
    return 0


if __name__ == "__main__":
    sys.exit(main())
