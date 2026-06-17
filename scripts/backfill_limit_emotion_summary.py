"""回填 limit_emotion_summary_daily (涨跌停情绪综合分).

用法:
    python scripts/backfill_limit_emotion_summary.py [--days=60] [--force]

数据流:
  - 走 duckdb.daily_raw + limit_repo.get_today_limit_snapshot
  - 单日计算: 涨跌停比 / 炸板率 / 昨日涨停收益 / composite
  - 落盘: INSERT OR REPLACE INTO limit_emotion_summary_daily

回填窗口: 从 --days 天前到今天, 跳过周末/节假日 (无 daily_raw 数据).
强制重算: --force 会覆盖已有记录.
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
from backend.repositories.market.limit_repo import (
    calc_limit_emotion_summary,
    save_limit_emotion_summary,
)
from backend.services.stock.trading_calendar import is_trading_day, previous_trading_day

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("backfill_limit_emotion_summary")


def _has_raw_data(trade_date: date) -> bool:
    """检查 daily_raw 在指定日是否有数据."""
    con = get_conn()
    r = con.execute(
        "SELECT 1 FROM daily_raw WHERE trade_date = ? LIMIT 1",
        [trade_date],
    ).fetchone()
    return r is not None


def _les_exists(trade_date: date) -> bool:
    con = get_conn()
    r = con.execute(
        "SELECT 1 FROM limit_emotion_summary_daily WHERE trade_date = ?",
        [trade_date],
    ).fetchone()
    return r is not None


def _walk_trading_days(start: date, end: date) -> list[date]:
    out: list[date] = []
    cur = start
    while cur <= end:
        if is_trading_day(cur):
            out.append(cur)
        cur += timedelta(days=1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="回填 limit_emotion_summary_daily 到 duckdb")
    ap.add_argument("--days", type=int, default=60,
                    help="回填窗口天数 (默认 60, 内部会过滤非交易日)")
    ap.add_argument("--force", action="store_true", help="覆盖已有记录")
    args = ap.parse_args()

    today = date.today()
    start = today - timedelta(days=args.days)
    log.info("回填窗口: %s ~ %s, force=%s", start.isoformat(), today.isoformat(), args.force)

    dates = _walk_trading_days(start, today)
    log.info("候选交易日 %d 天", len(dates))

    t0 = time.time()
    done = skip = fail = 0

    for i, td in enumerate(dates):
        if not args.force and _les_exists(td):
            skip += 1
            continue
        if not _has_raw_data(td):
            log.debug("  %s 跳过 (无 daily_raw 数据)", td)
            continue
        try:
            # prev_trade_date 用 trading_calendar 算, 而不是 -1 天,
            # 避免回填节假日的时候 prev 跑错 (虽然 daily_raw 缺失会被 has_raw_data 挡掉)
            try:
                prev = previous_trading_day(td)
            except Exception:
                prev = None
            payload = calc_limit_emotion_summary(td, prev_trade_date=prev)
            save_limit_emotion_summary(payload)
            done += 1
            log.info(
                "[%d/%d] %s 落盘: composite=%.2f (%s) "
                "up/down=%d/%d (ratio=%.1f) "
                "bb=%.1f%% yest_avg=%s",
                i + 1, len(dates), td,
                payload["compositeScore"], payload["level"],
                payload["limitUpCount"], payload["limitDownCount"],
                payload["limitUpDownRatio"],
                (payload["breakBoardRate"] or 0) * 100,
                f"{payload['yesterdayLimitUpAvgReturn']}%"
                if payload["yesterdayLimitUpAvgReturn"] is not None else "n/a",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("  %s 失败: %s", td, exc)
            fail += 1

    elapsed = time.time() - t0
    log.info("完成: 写入 %d 跳过 %d 失败 %d | 耗时 %.1fs",
             done, skip, fail, elapsed)
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
