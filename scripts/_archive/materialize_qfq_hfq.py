"""Compute cumulative adj_factors and materialize daily_qfq / daily_hfq.

Algorithm (per code, in chronological order):
  adj_factor[t] = product of all (1 + ratio[i]) for corp_events with ex_date[i] > t

  walk: sort events DESC by ex_date, sort dates ASC.
        for each trade_date, multiply factor in for each event whose ex_date
        has just passed.

Performance
-----------
  ~28M raw rows, ~few hundred K events total.
  Per-code single pass: O(D + E) where D = days, E = events for that code.
  Total: < 60 s for the full backfill on a modern box.

Output
------
  adj_factors  : (code, trade_date, factor)
  daily_qfq    : (code, trade_date, o/h/l/c × factor, volume, amount, factor)
  daily_hfq    : (code, trade_date, o/h/l/c × base_factor, ...) where
                 base_factor = factor at the earliest trade_date for that code
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb  # noqa: E402

from backend.adapters.market.duckdb_store import get_conn  # noqa: E402


def _load_events(con) -> dict[str, list[tuple[date, float]]]:
    """code → list of (ex_date, factor) sorted ASC by ex_date."""
    rows = con.execute(
        "SELECT code, ex_date, factor FROM corp_events ORDER BY code, ex_date"
    ).fetchall()
    out: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for code, ex_date, factor in rows:
        # DuckDB DECIMAL comes back as Decimal; force float for arithmetic.
        out[code].append((ex_date, float(factor)))
    return out


def _load_dates(con) -> dict[str, list[date]]:
    """code → list of trade_date sorted ASC."""
    rows = con.execute(
        "SELECT code, trade_date FROM daily_raw ORDER BY code, trade_date"
    ).fetchall()
    out: dict[str, list[date]] = defaultdict(list)
    for code, td in rows:
        out[code].append(td)
    return out


def _compute_factors(events_by_code: dict, dates_by_code: dict) -> list[tuple]:
    """For each (code, trade_date) compute cumulative product of factors for
    events with ex_date > trade_date.

    Returns list of (code, trade_date, factor) tuples ready for bulk insert.
    """
    out: list[tuple] = []
    for code, dates in dates_by_code.items():
        events = events_by_code.get(code, [])
        if not events:
            # No corp events: factor = 1.0 for all dates
            for td in dates:
                out.append((code, td, 1.0))
            continue
        # events are already ASC by ex_date. Walk dates ASC, multiply in any
        # events whose ex_date is strictly after the current date.
        e_idx = 0
        cur = 1.0
        for td in dates:
            while e_idx < len(events) and events[e_idx][0] > td:
                cur *= events[e_idx][1]
                e_idx += 1
            out.append((code, td, cur))
    return out


def _base_factor_per_code(factors: list[tuple]) -> dict[str, float]:
    """The factor at the earliest trade_date for each code. Used for hfq."""
    base: dict[str, float] = {}
    for code, _td, factor in factors:
        if code not in base:
            base[code] = factor
    return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-qfq", action="store_true",
                    help="Only compute adj_factors; skip materializing daily_qfq/hfq.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Compute but don't write; print summary only.")
    args = ap.parse_args()

    con = get_conn()
    print("loading events and dates...")
    t0 = time.time()
    events_by_code = _load_events(con)
    dates_by_code = _load_dates(con)
    n_events = sum(len(v) for v in events_by_code.values())
    n_dates = sum(len(v) for v in dates_by_code.values())
    n_codes = len(dates_by_code)
    print(f"  {n_events:,} events across {len(events_by_code):,} codes")
    print(f"  {n_dates:,} trade_dates across {n_codes:,} codes")
    print()

    print("computing cumulative factors...")
    factors = _compute_factors(events_by_code, dates_by_code)
    print(f"  computed {len(factors):,} (code, trade_date, factor) tuples "
          f"in {time.time() - t0:.1f}s")

    # Distribution check
    factor_max = max(f for _, _, f in factors)
    factor_min = min(f for _, _, f in factors)
    factor_eq_1 = sum(1 for _, _, f in factors if abs(f - 1.0) < 1e-9)
    print(f"  factor range: [{factor_min:.6f}, {factor_max:.6f}]")
    print(f"  factor == 1.0: {factor_eq_1:,} / {len(factors):,}  "
          f"({factor_eq_1/len(factors)*100:.1f}%)")
    print()

    if args.dry_run:
        print("dry-run; not writing")
        return

    # --- 1. Write adj_factors --------------------------------------------
    print("writing adj_factors...")
    con.execute("TRUNCATE adj_factors")
    # 28M rows via executemany is ~500× slower than register+INSERT (profiled:
    # 161s/40k rows = ~31 hours for 28M). Build a pandas frame in chunks
    # and stream via DuckDB's scan-pushdown.
    import pandas as pd                                  # noqa: PLC0415
    CHUNK = 2_000_000
    n_factors = len(factors)
    for i in range(0, n_factors, CHUNK):
        chunk = factors[i:i + CHUNK]
        df = pd.DataFrame(chunk, columns=["code", "trade_date", "factor"])
        con.register("_adjf_chunk", df)
        con.execute(
            "INSERT INTO adj_factors (code, trade_date, factor) "
            "SELECT code, trade_date, factor FROM _adjf_chunk"
        )
        con.unregister("_adjf_chunk")
        print(f"    + {min(i + CHUNK, n_factors):>10,} / {n_factors:,}")
    print(f"  adj_factors: {n_factors:,} rows")
    print()

    if args.skip_qfq:
        print("done (skip_qfq)")
        return

    # --- 2. Materialize daily_qfq ----------------------------------------
    print("materializing daily_qfq...")
    con.execute("TRUNCATE daily_qfq")
    # JOIN with daily_raw, multiply OHLC by factor. volume/amount unchanged.
    con.execute("""
        INSERT INTO daily_qfq (code, trade_date, open, high, low, close,
                               volume, amount, adj_factor, ingested_at)
        SELECT d.code, d.trade_date,
               d.open * a.factor, d.high * a.factor, d.low * a.factor,
               d.close * a.factor,
               d.volume, d.amount, a.factor, current_timestamp
          FROM daily_raw d
          JOIN adj_factors a
            ON d.code = a.code AND d.trade_date = a.trade_date
    """)
    n_qfq = con.execute("SELECT count(*) FROM daily_qfq").fetchone()[0]
    print(f"  daily_qfq: {n_qfq:,} rows")
    print()

    # --- 3. Materialize daily_hfq ----------------------------------------
    # hfq = raw × base_factor (constant per code, equals factor at earliest date)
    print("materializing daily_hfq...")
    con.execute("TRUNCATE daily_hfq")
    con.execute("""
        WITH base AS (
            SELECT code, factor AS base_factor
              FROM adj_factors a1
             WHERE trade_date = (
                   SELECT MIN(trade_date) FROM adj_factors a2
                    WHERE a2.code = a1.code
             )
        )
        INSERT INTO daily_hfq (code, trade_date, open, high, low, close,
                               volume, amount, adj_factor, ingested_at)
        SELECT d.code, d.trade_date,
               d.open * b.base_factor, d.high * b.base_factor,
               d.low * b.base_factor, d.close * b.base_factor,
               d.volume, d.amount, b.base_factor, current_timestamp
          FROM daily_raw d
          JOIN base b ON d.code = b.code
    """)
    n_hfq = con.execute("SELECT count(*) FROM daily_hfq").fetchone()[0]
    print(f"  daily_hfq: {n_hfq:,} rows")
    print()

    print(f"done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
