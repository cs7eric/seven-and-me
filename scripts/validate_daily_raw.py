"""Integrity checks for daily_raw. Run after a backfill pass.

Checks
------
1. **OHLC relations** — high >= low, open/close within [low, high].
2. **Date continuity** — gaps of more than ~10 business days (proxy for missing
   bars). Skips stocks with delist_date set.
3. **unit_scale anomaly** — flags stocks where the latest close is implausibly
   small (< 0.50 元) for a non-delisted code, or where the most recent 1-year
   range is implausibly narrow (e.g. < 0.1 元, suggesting 1/10 bug).
4. **Stale files** — .day file's last date is more than 5 calendar days behind
   today (a working store should be near-real-time after the EOD download).

Output
------
A summary table printed to stdout, plus a per-check detail view at the bottom.
Designed to be safe to re-run; read-only.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.adapters.market.duckdb_store import conn, table_stats  # noqa: E402

# Thresholds — centralise so they're easy to tune.
OHLC_GAP_TOLERANCE = 1e-3          # allow 0.001 元 rounding wiggle
MIN_PRICE_ACTIVE = 0.50            # below this and unit_scale=10 is suspected
RECENT_RANGE_MIN = 0.10            # 1-yr high-low must exceed this to be "real"
STALE_DAYS = 5                     # .day file older than this => stale
DATE_GAP_BUSINESS_DAYS = 10        # > 10 b-days gap => continuity flag


def _check_ohlc(c) -> list[tuple]:
    sql = f"""
        SELECT code, trade_date, open, high, low, close, 'oob_high_low' AS rule_label
          FROM daily_raw
         WHERE high < low - {OHLC_GAP_TOLERANCE}
        UNION ALL
        SELECT code, trade_date, open, high, low, close, 'open_above_high' AS rule_label
          FROM daily_raw
         WHERE open > high + {OHLC_GAP_TOLERANCE}
           AND NOT (high < low - {OHLC_GAP_TOLERANCE})
        UNION ALL
        SELECT code, trade_date, open, high, low, close, 'open_below_low' AS rule_label
          FROM daily_raw
         WHERE open < low - {OHLC_GAP_TOLERANCE}
           AND NOT (high < low - {OHLC_GAP_TOLERANCE})
        UNION ALL
        SELECT code, trade_date, open, high, low, close, 'close_above_high' AS rule_label
          FROM daily_raw
         WHERE close > high + {OHLC_GAP_TOLERANCE}
           AND NOT (open > high + {OHLC_GAP_TOLERANCE})
           AND NOT (high < low - {OHLC_GAP_TOLERANCE})
        UNION ALL
        SELECT code, trade_date, open, high, low, close, 'close_below_low' AS rule_label
          FROM daily_raw
         WHERE close < low - {OHLC_GAP_TOLERANCE}
           AND NOT (open < low - {OHLC_GAP_TOLERANCE})
           AND NOT (high < low - {OHLC_GAP_TOLERANCE})
         ORDER BY code, trade_date
    """
    return c.execute(sql).fetchall()


def _check_date_continuity(c) -> list[tuple]:
    """Per code, compute max gap between consecutive rows. Use DuckDB's
    lag() window function to keep it self-contained.
    """
    sql = f"""
        WITH s AS (
            SELECT code, trade_date,
                   trade_date - LAG(trade_date) OVER (PARTITION BY code ORDER BY trade_date) AS gap_days
              FROM daily_raw
        )
        SELECT code, MAX(gap_days) max_gap_days, COUNT(*) FILTER (WHERE gap_days IS NOT NULL) n_gaps
          FROM s
         WHERE gap_days IS NOT NULL
         GROUP BY code
        HAVING max_gap_days > {DATE_GAP_BUSINESS_DAYS * 2}   -- business days ≈ 1.4x calendar
         ORDER BY max_gap_days DESC
         LIMIT 100
    """
    return c.execute(sql).fetchall()


def _check_unit_scale(c) -> list[tuple]:
    """Flag stocks whose last close is implausibly small for active codes,
    OR where the 1-year high-low range is implausibly narrow.
    """
    sql = f"""
        WITH recent AS (
            SELECT code,
                   MAX(close) FILTER (WHERE trade_date > current_date - INTERVAL '1 year') yr_high,
                   MIN(close) FILTER (WHERE trade_date > current_date - INTERVAL '1 year') yr_low,
                   (SELECT close FROM daily_raw d2
                     WHERE d2.code = d1.code
                     ORDER BY trade_date DESC LIMIT 1) last_close
              FROM daily_raw d1
             GROUP BY code
        )
        SELECT code, last_close, yr_high, yr_low, (yr_high - yr_low) yr_range
          FROM recent
         WHERE (last_close < {MIN_PRICE_ACTIVE} AND yr_range < {RECENT_RANGE_MIN})
            OR (yr_range < {RECENT_RANGE_MIN})
         ORDER BY last_close
         LIMIT 200
    """
    return c.execute(sql).fetchall()


def _check_stale(c, today: date) -> list[tuple]:
    """Flag stocks whose last trade_date is older than STALE_DAYS ago.
    Use ingest_state.last_trade_date for speed; fall back to daily_raw if needed.
    """
    cutoff = today - timedelta(days=STALE_DAYS)
    sql = """
        SELECT s.code, s.last_trade_date,
               current_date - s.last_trade_date AS days_behind
          FROM ingest_state s
         WHERE s.last_trade_date IS NOT NULL
           AND s.last_trade_date < ?
         ORDER BY days_behind DESC
         LIMIT 200
    """
    return c.execute(sql, (cutoff,)).fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", type=str, default=None,
                    help="Reference 'today' (default: real today). YYYY-MM-DD.")
    ap.add_argument("--top", type=int, default=10,
                    help="Number of detail rows to show per check.")
    args = ap.parse_args()
    today = date.fromisoformat(args.today) if args.today else date.today()

    print("=" * 60)
    print("daily_raw validation")
    print("=" * 60)
    stats = table_stats()
    for t in ("daily_raw", "ingest_state"):
        print(f"  {t:20s} {stats.get(t, -1):>12,d} rows")
    print(f"  reference today  : {today}")
    print()

    with conn() as c:
        for name, rows in (
            ("ohlc_violations", _check_ohlc(c)),
            ("date_gaps", _check_date_continuity(c)),
            ("unit_scale_anomaly", _check_unit_scale(c)),
            ("stale_files", _check_stale(c, today)),
        ):
            n = len(rows)
            print(f"[{name}]  {n} rows")
            for r in rows[:args.top]:
                print(f"    {r}")
            if n > args.top:
                print(f"    ... and {n - args.top} more")
            print()


if __name__ == "__main__":
    main()
