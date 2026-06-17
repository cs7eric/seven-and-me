"""回填 MA 计数 + 宽基指数收益 持久化数据.

用法:
    python scripts/backfill_ma_count_and_returns.py [--days=60] [--force]

数据流:
  - MA 计数: 对 daily_qfq 跑 calc_ma_count(每个交易日) → 落 ma_count_daily
  - 指数收益: 对 5/10/20/60 四个窗口跑 get_index_returns(每个交易日) → 落 index_returns_daily

回填窗口: 从 --days 天前到今天, 跳过周末, 跳过没数据的日 (是周末/节假日或 daily_qfq 缺失).
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
from backend.repositories.market.indicator_repo import calc_ma_count, save_ma_count
from backend.repositories.market.index_repo import (
    get_index_returns_as_of, save_index_returns,
)
from backend.services.stock.trading_calendar import is_trading_day

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("backfill_metrics")


def _walk_trading_days(start: date, end: date) -> list[date]:
    """从 start 到 end (含) 之间的所有交易日."""
    out: list[date] = []
    cur = start
    while cur <= end:
        if is_trading_day(cur):
            out.append(cur)
        cur += timedelta(days=1)
    return out


def _has_daily_qfq_data(trade_date: date) -> bool:
    """检查 daily_qfq 在指定日是否有数据 (MA 计数前提)."""
    con = get_conn()
    r = con.execute(
        "SELECT COUNT(*) FROM daily_qfq WHERE trade_date = ? LIMIT 1",
        [trade_date],
    ).fetchone()
    return bool(r and r[0] > 0)


def _has_index_daily_data(trade_date: date) -> bool:
    """检查 index_daily_raw 在指定日是否有 2 只指数的数据."""
    con = get_conn()
    r = con.execute(
        "SELECT COUNT(DISTINCT code) FROM index_daily_raw WHERE trade_date = ?",
        [trade_date],
    ).fetchone()
    return bool(r and r[0] >= 2)


def _ma_exists(trade_date: date) -> bool:
    con = get_conn()
    r = con.execute("SELECT 1 FROM ma_count_daily WHERE trade_date = ?", [trade_date]).fetchone()
    return r is not None


def _index_returns_exist(trade_date: date) -> bool:
    con = get_conn()
    r = con.execute(
        "SELECT COUNT(DISTINCT window_days) FROM index_returns_daily WHERE trade_date = ?",
        [trade_date],
    ).fetchone()
    return bool(r and r[0] >= 4)


def main() -> int:
    ap = argparse.ArgumentParser(description="回填 MA 计数 + 指数收益到 duckdb")
    ap.add_argument("--days", type=int, default=60,
                    help="回填窗口天数 (默认 60, 包含周末/节假日, 内部会过滤)")
    ap.add_argument("--force", action="store_true",
                    help="覆盖已有记录 (默认跳过已有)")
    ap.add_argument("--skip-ma", action="store_true",
                    help="跳过 MA 计数 (只跑指数)")
    ap.add_argument("--skip-index", action="store_true",
                    help="跳过指数收益 (只跑 MA)")
    ap.add_argument("--index-windows", type=str, default="5,10,20,60",
                    help="指数收益窗口, 逗号分隔 (默认 5,10,20,60)")
    args = ap.parse_args()

    today = date.today()
    start = today - timedelta(days=args.days)
    windows = [int(x) for x in args.index_windows.split(",") if x.strip()]
    log.info("回填窗口: %s ~ %s, 指数 windows=%s, force=%s",
             start.isoformat(), today.isoformat(), windows, args.force)

    dates = _walk_trading_days(start, today)
    log.info("候选交易日 %d 天", len(dates))

    t0 = time.time()
    ma_done = ma_skip = ma_fail = 0
    ir_done = ir_skip = ir_fail = 0

    for i, td in enumerate(dates):
        # ----- MA 计数 -----
        if not args.skip_ma and _has_daily_qfq_data(td):
            if not args.force and _ma_exists(td):
                ma_skip += 1
            else:
                try:
                    payload = calc_ma_count(td)
                    save_ma_count(payload)
                    ma_done += 1
                    log.info("[%d/%d] MA %s 落盘: aboveBoth=%d/%d (%.1f%%)",
                             i + 1, len(dates), td,
                             payload["aboveBoth"], payload["totalEligible"],
                             payload["pctAboveBoth"])
                except Exception as exc:  # noqa: BLE001
                    log.warning("  MA %s 失败: %s", td, exc)
                    ma_fail += 1
        elif not args.skip_ma:
            log.debug("  MA %s 跳过 (无 daily_qfq 数据)", td)

        # ----- 指数收益 -----
        if not args.skip_index and _has_index_daily_data(td):
            if not args.force and _index_returns_exist(td):
                ir_skip += 1
            else:
                try:
                    for w in windows:
                        # 用 as_of_date 算: 让每个历史日算的是当时点 N 日累计收益,
                        # 而不是用最新 close 算的 (那会让所有历史日都长得一样)
                        items = get_index_returns_as_of(w, td)
                        save_index_returns(w, items)
                    ir_done += 1
                    log.info(
                        "[%d/%d] index %s 落盘 (windows=%s): %s",
                        i + 1, len(dates), td, windows,
                        [(it["name"], it["returnPct"]) for it in items],
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("  index %s 失败: %s", td, exc)
                    ir_fail += 1
        elif not args.skip_index:
            log.debug("  index %s 跳过 (无 index_daily_raw 数据)", td)

    elapsed = time.time() - t0
    log.info(
        "完成: MA 写入 %d 跳过 %d 失败 %d | 指数 写入 %d 跳过 %d 失败 %d | 耗时 %.1fs",
        ma_done, ma_skip, ma_fail, ir_done, ir_skip, ir_fail, elapsed,
    )
    return 0 if not (ma_fail or ir_fail) else 1


if __name__ == "__main__":
    sys.exit(main())
