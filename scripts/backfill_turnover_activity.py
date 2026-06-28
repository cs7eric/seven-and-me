"""成交活跃度 PostgreSQL 回填脚本.

计算公式: ratio = 当日全市场成交额 / 过去 20 日平均成交额
数据源: ClickHouse daily_raw.amount (999999 + 399001 成交额求和, 元→亿元)
目标表: PostgreSQL msi_turnover_activity_daily

幂等: 通过 repository upsert 重复跑不写脏.

用法:
    python scripts/backfill_turnover_activity.py
    python scripts/backfill_turnover_activity.py --days=60
    python scripts/backfill_turnover_activity.py --start=2026-06-01 --end=2026-06-17
    python scripts/backfill_turnover_activity.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
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

_TARGET_TRADE_DATE_ENV = "MINIMAX_TARGET_TRADE_DATE"


def _resolve_end_date() -> date:
    value = (os.environ.get(_TARGET_TRADE_DATE_ENV) or "").strip()
    if not value:
        return date.today()
    return date.fromisoformat(value)


def main(argv: list[str] | None = None) -> int:
    """成交活跃度 PostgreSQL 回填入口."""
    ap = argparse.ArgumentParser(description="成交活跃度 PostgreSQL 回填")
    ap.add_argument("--days", type=int, default=60, help="回填最近 N 天 (默认 60)")
    ap.add_argument("--start", type=str, default=None, help="起始日 YYYY-MM-DD")
    ap.add_argument("--end", type=str, default=None, help="结束日 YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划, 不执行")
    args = ap.parse_args(argv)

    from backend.repositories.market.turnover_activity_repo import (
        calc_turnover_activity,
        get_turnover_activity_source_coverage,
        get_turnover_activity_source_dates,
        save_turnover_activity,
        _add_score,
    )

    coverage = get_turnover_activity_source_coverage()
    db_min = coverage.get("firstDate")
    db_max = coverage.get("lastDate")
    if db_min is None or db_max is None:
        log.warning("daily_raw 缺少 999999 + 399001 完整成交额数据, 请先确认 TDX 日线已回填")
        return 1

    end_date = _resolve_end_date()
    if args.start:
        start = date.fromisoformat(args.start)
    else:
        start = max(db_min, end_date - timedelta(days=args.days))
    if args.end:
        end = date.fromisoformat(args.end)
    else:
        end = min(db_max, end_date)

    if start > end:
        log.warning("start=%s > end=%s, 无数据可回填", start, end)
        return 0

    trade_dates = get_turnover_activity_source_dates(start, end)
    log.info(
        "daily_raw(999999+399001) 在 %s ~ %s 中共 %d 个交易日 (%s=%s)",
        start,
        end,
        len(trade_dates),
        _TARGET_TRADE_DATE_ENV,
        end_date,
    )
    if args.dry_run:
        log.info("[dry-run] 不会执行写入")
        return 0

    t0 = time.time()
    ok_count = 0
    fail_count = 0
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
