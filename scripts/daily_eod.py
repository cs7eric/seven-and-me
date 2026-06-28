"""End-of-day pipeline orchestrator.

Runs each trading day after market close:

  1. initial_backfill.py          — pull .day files → ClickHouse daily_raw
  2. fetch_eltdx_adjusted_kline.py — pull qfq/hfq via eltdx → ClickHouse daily_qfq/daily_hfq
  3. fetch_index_history.py       — pull 上证指数/沪深300/中证1000 daily K → ClickHouse index_daily_raw
                                     (Market Pulse "宽基指数 5 日收益" 用)
  4. backfill_ma_count_and_returns.py — 算当日 MA 计数 + 5/10/20/60 日收益快照
                                     → 落 PostgreSQL MSI 表
                                    (cache-aside: 让 Market Pulse 趋势图 0.8ms 查)

Each step logs to stdout with timing. Steps are independent: failure of one
does not block the next.

Trading-day check: weekday ∈ {Mon..Fri}. Holiday skipping is left to the
ingest_state cursor — if a day has no new prices, the steps become no-ops.

Usage:
  python scripts/daily_eod.py
  python scripts/daily_eod.py --skip-qfq      # for fast iteration
  python scripts/daily_eod.py --no-date-check # run on any day
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent

STEPS = [
    ("1/4 拉日线 → CH daily_raw",                     ["initial_backfill.py"]),
    ("2/4 拉 qfq/hfq → CH daily_qfq/daily_hfq",       ["fetch_eltdx_adjusted_kline.py"]),
    ("3/4 拉宽基指数 → CH index_daily_raw",            ["fetch_index_history.py", "--days=2"]),
    ("4/4 算+落 MA 计数 + 指数收益快照 → PG",           ["backfill_ma_count_and_returns.py", "--days=1", "--force"]),
]


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5  # Mon=0..Fri=4


def run_step(label: str, args: list[str]) -> bool:
    script = SCRIPTS / args[0]
    print()
    print("=" * 70)
    print(f"  {label}  ({args[0]})")
    print("=" * 70)
    t0 = time.time()
    try:
        result = subprocess.run(
            [sys.executable, "-u", str(script), *args[1:]],
            check=False,
        )
    except Exception as exc:                                    # noqa: BLE001
        print(f"  ! {args[0]} crashed: {type(exc).__name__}: {exc}")
        return False
    elapsed = time.time() - t0
    status = "OK" if result.returncode == 0 else f"FAIL({result.returncode})"
    print(f"\n  [{args[0]}] {status}  in {elapsed:.1f}s")
    return result.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-qfq", action="store_true",
                    help="Skip qfq/hfq reconciliation step (step 2).")
    ap.add_argument("--skip-index", action="store_true",
                    help="Skip step 3 (index K-line pull).")
    ap.add_argument("--skip-metrics", action="store_true",
                    help="Skip step 4 (MA count + index returns snapshot).")
    ap.add_argument("--no-date-check", action="store_true",
                    help="Don't check weekday; run on any day.")
    ap.add_argument("--only", type=str, default=None,
                    help="Run only this step (1-8).")
    args = ap.parse_args()

    today = date.today()
    print(f"daily_eod  today={today}  {datetime.now().strftime('%H:%M:%S')}")
    if not args.no_date_check and not is_trading_day(today):
        print(f"  {today.strftime('%A')} — not a trading day, skipping")
        return 0

    steps = list(STEPS)
    if args.skip_qfq:
        steps = [s for s in steps if not s[0].startswith("2/")]
    if args.skip_index:
        steps = [s for s in steps if not s[0].startswith("3/")]
    if args.skip_metrics:
        steps = [s for s in steps if not s[0].startswith("4/")]
    if args.only:
        steps = [steps[int(args.only) - 1]]

    t0 = time.time()
    results = []
    for label, script_args in steps:
        ok = run_step(label, script_args)
        results.append((label, ok))
    total = time.time() - t0

    print()
    print("=" * 70)
    print(f"  daily_eod done in {total:.1f}s ({total/60:.1f} min)")
    print("=" * 70)
    for label, ok in results:
        print(f"  {'✓' if ok else '✗'}  {label}")
    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(main())
