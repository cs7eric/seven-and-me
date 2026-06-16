"""Pull 前复权 / 后复权 K-line directly from eltdx.

This REPLACES the corp_events + materialize pipeline: eltdx already computes
TDX's exact qfq/hfq factors internally (using get_gbbq + get_xdxr + get_factors),
so we just pull the result and store in daily_qfq / daily_hfq.

Architecture:
  1. Per-stock: get_adjusted_kline(period='day', adjust='qfq' | 'hfq') returns
     up to 800 bars (≈ 3.3 years of trading days). For older histories use
     get_adjusted_kline_all() with pagination, or run multiple passes with
     start offsets.
  2. Bulk insert via DuckDB register+INSERT (NOT executemany) — ~500× faster.
  3. Idempotent via INSERT OR IGNORE on (code, trade_date).

Speed
-----
eltdx connects over TCP, not HTTP. With persistent TdxClient per worker:
  - 1 connection setup ≈ 100 ms (once per worker, reused)
  - 1 get_adjusted_kline call ≈ 100-300 ms
With 32 workers:
  - 12020 stocks / 32 = 376 batches × 200 ms ≈ 75 s
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from threading import Lock, local

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb  # noqa: E402
import pandas as pd  # noqa: E402

from eltdx import TdxClient  # noqa: E402

from backend.adapters.market.duckdb_store import (  # noqa: E402
    get_conn,
    init_schema,
    table_stats,
)

# ---------- thread-local TdxClient -------------------------------

_tls = local()


def _get_client(timeout: int = 8) -> TdxClient:
    """One TdxClient per worker thread (one TCP connection)."""
    if not hasattr(_tls, "client"):
        _tls.client = TdxClient(timeout=timeout)
    return _tls.client


# ---------- per-stock fetch ---------------------------------------

# 6-digit code → market prefix
def _to_full_code(code: str) -> str:
    return f"sh{code}" if code.startswith(("5", "6", "9")) else f"sz{code}"


def _bars_to_rows(code: str, bars, target_table: str):
    """Convert eltdx bars into (code, trade_date, open, high, low, close,
    volume, amount, adj_factor?) tuples ready for bulk insert.
    """
    rows = []
    for r in bars:
        rows.append((
            code,
            r.time.date(),
            float(r.open),
            float(r.high),
            float(r.low),
            float(r.close),
            int(r.volume_lots) if r.volume_lots is not None else 0,
            float(r.amount) if r.amount is not None else 0.0,
        ))
    return rows


def _fetch_one(code: str, adjust: str, max_retries: int = 3) -> tuple[list, str | None]:
    """Fetch adjusted K-line for one stock, with retry+backoff.

    Retry policy:
      - Empty result (no bars returned): retry — could be transient
      - Timeout / ConnectionError / OSError: retry
      - ProtocolError ("invalid code", "invalid kline date"): do NOT retry —
        these are stock-data issues, not network problems

    Returns (rows, err_msg). err_msg is set only when retries exhausted
    or error is non-retriable.
    """
    last_err: str | None = None
    backoffs = [1, 3, 9]                # seconds before retries 1, 2, 3
    retriable = (TimeoutError, ConnectionError, OSError)

    for attempt in range(max_retries + 1):
        try:
            client = _get_client()
            full_code = _to_full_code(code)
            series = client.get_adjusted_kline_all(
                "day", full_code, adjust=adjust, page_size=800, max_pages=200,
            )
            bars = series.bars if hasattr(series, "bars") else series.items
            if bars:
                return _bars_to_rows(code, bars, "daily_qfq"), None
            # Empty: treat as transient (could be server blip).
            last_err = "empty result"
        except retriable as exc:                                    # noqa: PERF203
            last_err = f"{type(exc).__name__}: {exc}"
        except Exception as exc:                                    # noqa: BLE001
            # Non-retriable (e.g. ProtocolError on bad code). Bail.
            return [], f"{type(exc).__name__}: {exc}"

        if attempt < max_retries:
            time.sleep(backoffs[min(attempt, len(backoffs) - 1)])

    return [], last_err or "empty after retries"


# ---------- main ---------------------------------------------------

def _done_codes(adjust: str) -> set[str]:
    con = get_conn()
    rows = con.execute(
        f"SELECT code FROM ingest_state "
        f"WHERE last_status LIKE ? || '_ok%'",
        [adjust],
    ).fetchall()
    return {r[0] for r in rows}


def _mark_done(code: str, adjust: str, n_rows: int) -> None:
    con = get_conn()
    con.execute(
        """
        MERGE INTO ingest_state t
        USING (SELECT ? AS code, ? AS status) s
        ON t.code = s.code
        WHEN MATCHED THEN
            UPDATE SET last_run_at = current_timestamp, last_status = s.status
        WHEN NOT MATCHED THEN
            INSERT (code, day_file_path, processed_bytes, last_run_at, last_status)
            VALUES (s.code, '', 0, current_timestamp, s.status)
        """,
        (code, f"{adjust}_ok|rows={n_rows}"),
    )


def _bulk_insert(adjust: str, rows: list) -> int:
    """Register DataFrame + INSERT OR IGNORE. ~500× faster than executemany."""
    if not rows:
        return 0
    target = "daily_qfq" if adjust == "qfq" else "daily_hfq"
    df = pd.DataFrame(rows, columns=[
        "code", "trade_date", "open", "high", "low", "close", "volume", "amount",
    ])
    con = get_conn()
    con.register("_eltdx_staging", df)
    n = len(df)
    con.execute(
        f"INSERT OR IGNORE INTO {target} "
        "(code, trade_date, open, high, low, close, volume, amount, "
        " adj_factor, ingested_at) "
        "SELECT code, trade_date, open, high, low, close, volume, amount, "
        "       1.0, current_timestamp FROM _eltdx_staging"
    )
    con.unregister("_eltdx_staging")
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adjust", choices=["qfq", "hfq", "both"], default="both")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--no-resume", action="store_true")
    ap.add_argument("--retry-missing", action="store_true",
                    help="Only fetch codes that are missing in daily_{adj}. "
                         "Use to retry codes that failed in a previous run.")
    args = ap.parse_args()

    init_schema()
    con = get_conn()
    print("SCHEMA state:")
    for t, n in table_stats().items():
        print(f"  {t:20s} {n:>12,d}")
    print()

    rows = con.execute(
        "SELECT DISTINCT code FROM daily_raw ORDER BY code"
    ).fetchall()
    all_codes = [r[0] for r in rows]

    skip = set()
    if not args.no_resume:
        for adj in (["qfq"] if args.adjust == "qfq" else
                    ["hfq"] if args.adjust == "hfq" else ["qfq", "hfq"]):
            skip |= _done_codes(adj)
        before = len(all_codes)
        all_codes = [c for c in all_codes if c not in skip]
        print(f"resume: {len(skip)} codes already done, {len(all_codes)} remaining "
              f"(of {before} total)")

    if args.retry_missing:
        # Skip resume filter — codes marked 'ok|rows=0' but actually empty
        # in the table should still be retried. Restore full list.
        all_codes = [r[0] for r in con.execute(
            "SELECT DISTINCT code FROM daily_raw ORDER BY code"
        ).fetchall()]
        skip = set()
        print("retry-missing: ignoring resume filter (will retry even 'ok' codes)")

    if args.limit:
        all_codes = all_codes[:args.limit]
    print(f"plan: {len(all_codes)} stocks, {args.workers} workers, adjust={args.adjust}")
    print()

    t0 = time.time()
    adjusts = ["qfq", "hfq"] if args.adjust == "both" else [args.adjust]
    completed = 0
    err_count = 0
    grand_inserted = 0

    for adj in adjusts:
        if args.retry_missing:
            # Narrow the set per adjust if both — only fetch codes with NO row
            # in the target table.
            adj_target = f"daily_{adj}"
            miss = con.execute(f"""
                SELECT DISTINCT r.code
                  FROM daily_raw r
                 WHERE NOT EXISTS (SELECT 1 FROM {adj_target} t
                                    WHERE t.code = r.code)
                 ORDER BY r.code
            """).fetchall()
            missing_set = {r[0] for r in miss}
            adj_codes = [c for c in all_codes if c in missing_set]
        else:
            adj_codes = all_codes
        print(f"--- fetching {adj}: {len(adj_codes)} stocks ---")
        all_rows = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(_fetch_one, code, adj): code
                       for code in adj_codes}
            for fut in as_completed(futures):
                code = futures[fut]
                completed += 1
                try:
                    rows, err = fut.result()
                except Exception as exc:                           # noqa: BLE001
                    err = f"{type(exc).__name__}: {exc}"
                    rows = []
                if err:
                    err_count += 1
                    if err_count <= 5:
                        print(f"  ! {code}: {err}", flush=True)
                else:
                    all_rows.extend(rows)
                    _mark_done(code, adj, len(rows))

                if completed % 200 == 0 or completed == len(adj_codes):
                    elapsed = time.time() - t0
                    rate = completed / elapsed if elapsed else 0
                    eta = (len(adj_codes) - completed) / rate if rate else 0
                    print(
                        f"  [{completed:>6d}/{len(adj_codes)}]  "
                        f"{rate:>5.1f} stk/s  "
                        f"rows_buffered={len(all_rows):>9,}  "
                        f"err={err_count:>3d}  "
                        f"ETA {eta:>4.0f}s",
                        flush=True,
                    )

        print(f"  flushing {len(all_rows):,} rows to daily_{adj}...")
        n = _bulk_insert(adj, all_rows)
        grand_inserted += n
        print(f"  daily_{adj}: +{n:,} new rows (skipped dupes)")
        print()

    print(f"done in {time.time() - t0:.1f}s")
    print(f"  total new rows: {grand_inserted:,}")
    print(f"  errors: {err_count}")


if __name__ == "__main__":
    main()