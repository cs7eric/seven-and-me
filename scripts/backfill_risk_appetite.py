"""回填 risk_appetite_daily.

用法:
    python scripts/backfill_risk_appetite.py [--days=60] [--force]

数据流:
  - 沪深300 20日累计收益 + 511010/511090 20日累计收益 → spread_weighted
  - 走 ClickHouse daily_qfq (有完整历史, 沪深300 5200+ 行 / 511010 3200+ / 511090 720+)

回填窗口: 从 --days 天前到今天, 跳过周末/节假日 (无 daily_qfq 数据).
强制重算: --force 会覆盖已有记录.
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

from backend.adapters.market.clickhouse_store import query_one
from backend.config.database import session_scope
from backend.repositories.market.risk_appetite_repo import (
    calc_risk_appetite, save_risk_appetite,
)
from backend.repositories.market.market_pg_cynexus_repo import qname
from backend.services.stock.trading_calendar import is_trading_day
from sqlalchemy import text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("backfill_risk_appetite")
_TARGET_TRADE_DATE_ENV = "MINIMAX_TARGET_TRADE_DATE"


def _has_qfq_data(trade_date: date, codes: list[str]) -> bool:
    """检查 ClickHouse daily_qfq 在指定日 OR 之前是否有任一标的的数据."""
    if not codes:
        return False
    placeholders = ", ".join(["%s"] * len(codes))
    r = query_one(
        f"SELECT count() FROM daily_qfq WHERE trade_date <= %s AND code IN ({placeholders})",
        (trade_date, *codes),
    )
    return bool(r and r[0] > 0)


def _ra_exists(trade_date: date) -> bool:
    with session_scope() as db:
        r = db.execute(
            text(f"SELECT 1 FROM {qname('msi_risk_appetite_daily')} WHERE trade_date = :td AND deleted_at IS NULL LIMIT 1"),
            {"td": trade_date},
        ).first()
    return r is not None


def _walk_trading_days(start: date, end: date) -> list[date]:
    out: list[date] = []
    cur = start
    while cur <= end:
        if is_trading_day(cur):
            out.append(cur)
        cur += timedelta(days=1)
    return out


def _resolve_end_date() -> date:
    value = (os.environ.get(_TARGET_TRADE_DATE_ENV) or "").strip()
    if not value:
        return date.today()
    return date.fromisoformat(value)


def main() -> int:
    ap = argparse.ArgumentParser(description="回填 risk_appetite_daily 到 PostgreSQL")
    ap.add_argument("--days", type=int, default=60,
                    help="回填窗口天数 (默认 60, 内部会过滤非交易日)")
    ap.add_argument("--force", action="store_true", help="覆盖已有记录")
    args = ap.parse_args()

    end_date = _resolve_end_date()
    start = end_date - timedelta(days=args.days)
    log.info(
        "回填窗口: %s ~ %s, force=%s, %s=%s",
        start.isoformat(), end_date.isoformat(), args.force, _TARGET_TRADE_DATE_ENV, end_date.isoformat(),
    )

    dates = _walk_trading_days(start, end_date)
    log.info("候选交易日 %d 天", len(dates))

    t0 = time.time()
    done = skip = fail = 0
    codes = ["000300", "511010", "511090"]

    for i, td in enumerate(dates):
        if not args.force and _ra_exists(td):
            skip += 1
            continue
        if not _has_qfq_data(td, codes):
            log.debug("  %s 跳过 (无 daily_qfq 数据)", td)
            continue
        try:
            payload = calc_risk_appetite(td)
            save_risk_appetite(payload)
            done += 1
            log.info("[%d/%d] %s 落盘: spread_weighted=%.2f%%  "
                     "(hs300=%.2f%% / treasury=%.2f%%)",
                     i + 1, len(dates), td,
                     payload["spread"]["weighted"],
                     payload["hs300"]["returnPct"],
                     payload["treasury"]["weighted"]["returnPct"])
        except Exception as exc:  # noqa: BLE001
            log.warning("  %s 失败: %s", td, exc)
            fail += 1

    elapsed = time.time() - t0
    log.info("完成: 写入 %d 跳过 %d 失败 %d | 耗时 %.1fs",
             done, skip, fail, elapsed)
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
