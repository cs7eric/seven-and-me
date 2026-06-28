"""One-shot backfill: parse every TDX .day file under hsjday/ into ClickHouse daily_raw.

Strategy
--------
1. Enumerate .day files via ``tdx_downloader``.
2. For each file, parse with ``tdx_parser``. In this first pass we assume
   ``unit_scale = 1`` (the spec default); scale anomalies are surfaced via
   a separate validation step (see ``validate_daily_raw.py``) so we don't
   pay for an API round-trip per stock during the bulk load.
3. Bulk-insert into ClickHouse ``daily_raw`` in batches.
4. Append ``ingest_state`` rows so we can resume from the latest successful
   state for each code.

Speed
-----
~12k files, ~29M records total. On a modern box expect 5-15 min wall clock
for the full backfill. Use ``--limit N`` for a smoke test.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime
from pathlib import Path

# Make sibling scripts/ + backend/ importable.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from tdx_downloader import iter_day_files, DayFile  # noqa: E402
from tdx_parser import parse_day_file  # noqa: E402

from backend.adapters.market.clickhouse_store import command, insert, query_rows  # noqa: E402

BATCH_FILES = 200      # files per flush (≈ 1.4M rows / batch on avg)
PROGRESS_EVERY = 50    # files between progress logs


def _quote_ch_strings(values: list[str]) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


def _flush(dfs: list[pd.DataFrame]) -> int:
    """Insert all queued DataFrames into ClickHouse daily_raw. Returns total rows."""
    if not dfs:
        return 0
    big = pd.concat(dfs, ignore_index=True)
    if big.empty:
        return 0

    codes = sorted(str(c) for c in big["code"].dropna().unique())
    min_date = big["trade_date"].min()
    max_date = big["trade_date"].max()
    if codes:
        command(
            "ALTER TABLE daily_raw DELETE "
            f"WHERE code IN ({_quote_ch_strings(codes)}) "
            f"AND trade_date BETWEEN toDate('{min_date}') AND toDate('{max_date}')",
            settings={"mutations_sync": 1},
        )

    now = datetime.now()
    rows = [
        (
            str(r.code),
            r.trade_date,
            float(r.open),
            float(r.high),
            float(r.low),
            float(r.close),
            int(r.volume),
            float(r.amount),
            int(r.unit_scale),
            str(r.source),
            now,
        )
        for r in big.itertuples(index=False)
    ]
    insert(
        "daily_raw",
        rows,
        ["code", "trade_date", "open", "high", "low", "close", "volume", "amount", "unit_scale", "source", "ingested_at"],
    )
    return len(rows)


def _update_state(code: str, day_file: DayFile,
                  last_trade_date: date | None, unit_scale: int,
                  status: str, rows_inserted: int) -> None:
    insert(
        "ingest_state",
        [(
            code,
            str(day_file.path),
            int(day_file.size),
            last_trade_date,
            int(unit_scale),
            datetime.now(),
            f"{status}|rows={rows_inserted}",
        )],
        ["code", "day_file_path", "processed_bytes", "last_trade_date", "last_unit_scale", "last_run_at", "last_status"],
    )


def _done_codes() -> set[str]:
    rows = query_rows(
        """
        SELECT code
          FROM (
                SELECT code, argMax(last_status, last_run_at) AS last_status
                  FROM ingest_state
                 GROUP BY code
               )
         WHERE startsWith(last_status, 'ok')
        """
    )
    return {str(r[0]) for r in rows}


def backfill(limit: int | None = None,
             markets: tuple[str, ...] = ("sh", "sz", "bj"),
             unit_scale: int = 1,
             resume: bool = True) -> None:
    """Run the one-shot backfill.

    Args:
        limit:        if given, stop after this many files.
        markets:      which markets to include.
        unit_scale:   forced unit_scale for all files in this pass (1 = spec).
        resume:       if True, skip files already marked 'ok' in ingest_state.
    """
    all_files = list(iter_day_files(markets=markets))
    if resume:
        done = _done_codes()
        before = len(all_files)
        all_files = [f for f in all_files if f.code not in done]
        skipped = before - len(all_files)
        print(f"resume: skipping {skipped} already-done files, {len(all_files)} remaining")
    if limit is not None:
        all_files = all_files[:limit]
    print(f"plan: {len(all_files)} files, unit_scale={unit_scale}, batch={BATCH_FILES} files/flush")

    t0 = time.time()
    inserted_rows = 0
    bad_files = 0
    pending: list[pd.DataFrame] = []

    for i, df in enumerate(all_files, start=1):
        try:
            result = parse_day_file(df.path, api_close=None)
            # Force unit_scale if requested (overrides auto-detect).
            if unit_scale != result.unit_scale:
                ratio = unit_scale / result.unit_scale
                for col in ('open', 'high', 'low', 'close'):
                    result.df[col] = result.df[col] * ratio
                result.df['unit_scale'] = unit_scale
                result.unit_scale = unit_scale

            pending.append(result.df[['code', 'trade_date', 'open', 'high',
                                      'low', 'close', 'volume', 'amount',
                                      'unit_scale', 'source']])
            last_td = result.df['trade_date'].iloc[-1] if len(result.df) else None

            if len(pending) >= BATCH_FILES:
                inserted_rows += _flush(pending)
                pending.clear()

            _update_state(df.code, df, last_td, result.unit_scale,
                          'ok', len(result.df))

        except Exception as exc:
            bad_files += 1
            _update_state(df.code, df, None, unit_scale,
                          f'parse_error: {type(exc).__name__}', 0)
            if bad_files <= 5:
                print(f"  ! {df.filename}: {type(exc).__name__}: {exc}",
                      flush=True)

        if i % PROGRESS_EVERY == 0 or i == len(all_files):
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed else 0
            eta = (len(all_files) - i) / rate if rate else 0
            print(
                f"  [{i:>6d}/{len(all_files)}]  {rate:>6.1f} files/s"
                f"  rows={inserted_rows:>10,d}  bad={bad_files}"
                f"  ETA {eta:>5.0f}s",
                flush=True,
            )

    # Flush remainder.
    if pending:
        inserted_rows += _flush(pending)

    elapsed = time.time() - t0
    print()
    print(f"done in {elapsed:,.1f}s  ({elapsed/60:.1f} min)")
    print(f"  files: {len(all_files)} (bad: {bad_files})")
    print(f"  rows inserted: {inserted_rows:,}")


def main(argv: list[str] | None = None) -> int:
    """CLI 入口, 接受 argv 给 in-process 调用方."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="Process only first N files (smoke test).")
    ap.add_argument("--market", choices=["sh", "sz", "bj", "all"], default="all")
    ap.add_argument("--unit-scale", type=int, default=1,
                    help="Force unit_scale on every file (default 1 = spec).")
    ap.add_argument("--no-resume", action="store_true",
                    help="Process all files, ignoring ingest_state.")
    args = ap.parse_args(argv)
    markets = ("sh", "sz", "bj") if args.market == "all" else (args.market,)
    backfill(limit=args.limit, markets=markets, unit_scale=args.unit_scale,
             resume=not args.no_resume)
    return 0


if __name__ == "__main__":
    sys.exit(main())
