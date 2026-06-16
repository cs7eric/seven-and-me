"""End-of-day pipeline orchestrator.

Runs each trading day after market close:

  1. initial_backfill.py         — pull .day files → daily_raw
  2. fetch_eltdx_adjusted_kline.py — pull qfq/hfq via eltdx (parallel)
  3. fallback_indices_b_shares.py — copy raw → qfq/hfq for indices/B-shares
  4. fallback_etfs.py            — copy raw → qfq/hfq for 125 ETFs eltdx missed
  5. fallback_remaining_ashares.py — copy raw → qfq/hfq for 614 A-shares
                                    eltdx missed (mostly delisted)
  6. validate_daily_raw.py       — OHLC / gap / unit-scale / stale checks

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
    ("1/6 拉日线 → daily_raw",                       ["initial_backfill.py"]),
    ("2/6 拉 qfq/hfq via eltdx (parallel)",          ["fetch_eltdx_adjusted_kline.py"]),
    ("3/6 兜底 指数/B股 (raw → qfq/hfq)",             ["fallback_indices_b_shares.py"]),
    ("4/6 兜底 ETF (raw → qfq/hfq, 125 只)",          ["fallback_etfs.py"]),
    ("5/6 兜底 剩余 A 股 (raw → qfq/hfq, 614 只)",    ["fallback_remaining_ashares.py"]),
    ("6/6 完整性校验",                                ["validate_daily_raw.py"]),
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
                    help="Skip all qfq-related steps (steps 2-5).")
    ap.add_argument("--no-date-check", action="store_true",
                    help="Don't check weekday; run on any day.")
    ap.add_argument("--only", type=str, default=None,
                    help="Run only this step (1-6).")
    args = ap.parse_args()

    today = date.today()
    print(f"daily_eod  today={today}  {datetime.now().strftime('%H:%M:%S')}")
    if not args.no_date_check and not is_trading_day(today):
        print(f"  {today.strftime('%A')} — not a trading day, skipping")
        return 0

    steps = list(STEPS)
    if args.skip_qfq:
        steps = [s for s in steps if s[0].startswith(("1/", "6/"))]
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
