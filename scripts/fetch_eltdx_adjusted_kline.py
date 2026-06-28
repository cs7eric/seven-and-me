"""Pull 前复权 / 后复权 K-line directly from eltdx.

This REPLACES the corp_events + materialize pipeline: eltdx already computes
TDX's exact qfq/hfq factors internally (using get_gbbq + get_xdxr + get_factors),
so we just pull the result and store in daily_qfq / daily_hfq.

Architecture:
  1. Per-stock: get_adjusted_kline(period='day', adjust='qfq' | 'hfq') returns
     up to 800 bars (≈ 3.3 years of trading days). For older histories use
     get_adjusted_kline_all() with pagination, or run multiple passes with
     start offsets.
  2. Bulk insert into ClickHouse daily_qfq / daily_hfq.
  3. Idempotent via DELETE affected (code, trade_date) range then INSERT.

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
from threading import local

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from eltdx import TdxClient  # noqa: E402

from backend.adapters.market.clickhouse_store import command, insert, query_rows  # noqa: E402

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


def _bars_to_rows(code: str, bars):
    """Convert eltdx bars into ClickHouse row tuples."""
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
                return _bars_to_rows(code, bars), None
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
    rows = query_rows(
        """
        SELECT DISTINCT code
          FROM ingest_state
         WHERE startsWith(last_status, %s)
        """,
        (f"{adjust}_ok",),
    )
    return {r[0] for r in rows}


def _mark_done(code: str, adjust: str, n_rows: int, last_trade_date) -> None:
    insert(
        "ingest_state",
        [(
            code,
            "",
            0,
            last_trade_date,
            1,
            datetime.now(),
            f"{adjust}_ok|rows={n_rows}",
        )],
        ["code", "day_file_path", "processed_bytes", "last_trade_date", "last_unit_scale", "last_run_at", "last_status"],
    )


def _quote_ch_strings(values: list[str]) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


def _bulk_insert(adjust: str, rows: list) -> int:
    """Delete affected rows, then insert adjusted bars into ClickHouse."""
    if not rows:
        return 0
    target = "daily_qfq" if adjust == "qfq" else "daily_hfq"
    df = pd.DataFrame(rows, columns=[
        "code", "trade_date", "open", "high", "low", "close", "volume", "amount",
    ])
    codes = sorted(str(c) for c in df["code"].dropna().unique())
    min_date = df["trade_date"].min()
    max_date = df["trade_date"].max()
    if codes:
        command(
            f"ALTER TABLE {target} DELETE "
            f"WHERE code IN ({_quote_ch_strings(codes)}) "
            f"AND trade_date BETWEEN toDate('{min_date}') AND toDate('{max_date}')",
            settings={"mutations_sync": 1},
        )
    now = datetime.now()
    out_rows = [
        (
            str(r.code),
            r.trade_date,
            float(r.open),
            float(r.high),
            float(r.low),
            float(r.close),
            int(r.volume),
            float(r.amount),
            1.0,
            now,
        )
        for r in df.itertuples(index=False)
    ]
    insert(
        target,
        out_rows,
        ["code", "trade_date", "open", "high", "low", "close", "volume", "amount", "adj_factor", "ingested_at"],
    )
    return len(out_rows)


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

    rows = query_rows("SELECT DISTINCT code FROM daily_raw ORDER BY code")
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
        all_codes = [r[0] for r in query_rows("SELECT DISTINCT code FROM daily_raw ORDER BY code")]
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
            miss = query_rows(f"""
                SELECT DISTINCT r.code
                  FROM daily_raw r
                 WHERE r.code NOT IN (SELECT DISTINCT t.code FROM {adj_target} t)
                 ORDER BY r.code
            """)
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
                    last_trade_date = max((r[1] for r in rows), default=None)
                    _mark_done(code, adj, len(rows), last_trade_date)

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