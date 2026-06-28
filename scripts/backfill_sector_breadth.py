"""板块扩散 → market_pulse_sector_breadth_daily 回填.

数据源: PostgreSQL mkt_ths_industry_fund_flow_daily
  取所有 DISTINCT trade_date, 对每个日期聚合算 advancing/declining/flat/total/advance_pct,
  upsert 到 PostgreSQL msi_sector_breadth_daily.

幂等: 通过 repository upsert 重复跑不写脏.

用法:
    python scripts/backfill_sector_breadth.py
    python scripts/backfill_sector_breadth.py --days=365
    python scripts/backfill_sector_breadth.py --date=2026-06-16   # 单日
    python scripts/backfill_sector_breadth.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("backfill_sector_breadth")
_TARGET_TRADE_DATE_ENV = "MINIMAX_TARGET_TRADE_DATE"
load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _resolve_end_date() -> date:
    value = (os.environ.get(_TARGET_TRADE_DATE_ENV) or "").strip()
    if not value:
        return date.today()
    return date.fromisoformat(value)


def main() -> int:
    ap = argparse.ArgumentParser(description="回填板块扩散到 PostgreSQL")
    ap.add_argument("--days", type=int, default=365,
                    help="回填最近 N 天 (默认 365)")
    ap.add_argument("--date", type=str, default=None,
                    help="单日 YYYY-MM-DD, 只回填这一天")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="保留兼容; 本脚本默认覆盖写")
    args = ap.parse_args()

    end_date = _resolve_end_date()
    log.info("start: days=%s date=%s dry_run=%s %s=%s",
             args.days, args.date, args.dry_run, _TARGET_TRADE_DATE_ENV, end_date)

    from backend.repositories.market.sector_breadth_repo import (
        upsert_sector_breadth, coverage, get_sector_breadth_history,
    )

    # 单日模式
    if args.date:
        n = upsert_sector_breadth(args.date)
        log.info("upserted %d 行 (date=%s)", n, args.date)
        return 0 if n > 0 or args.dry_run else 1

    # 区间模式: 从 Postgres 行业资金流 alive 快照枚举最近交易日.
    # 这里不能再扫 DuckDB 旧 ths_industry_fund_flow_daily, 否则 scheduler 会永远停在
    # 旧链路最后一次导入日期, 看不到 17:15 新写入的 Postgres 2026-06-22 快照。
    from backend.config.database import session_scope
    from backend.repositories.market.ths_industry_fund_flow_repo import (
        ThsIndustryFundFlowRepository,
    )
    cutoff = end_date - timedelta(days=args.days)
    with session_scope() as db:
        repo = ThsIndustryFundFlowRepository(db)
        date_values = repo.list_trade_dates(
            scope="industry",
            limit=max(1, min(args.days + 16, 1000)),
        )
    dates: list[date] = []
    for value in reversed(date_values):
        td = date.fromisoformat(value) if isinstance(value, str) else value
        if td is None:
            continue
        if cutoff <= td <= end_date:
            dates.append(td)
    log.info("app.sector_fund_flow_daily_snapshots 命中 %d 天 (>= %s)", len(dates), cutoff)

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
        end=end_date.isoformat(),
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
