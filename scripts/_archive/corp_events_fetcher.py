"""One-shot (or daily) fetch of corp_events (送转分红) from AKShare.

Source: ``ak.stock_history_dividend_detail(symbol, indicator='分红')``
backed by Sina F10. For each stock returns:
    公告日期, 送股 (per 10 shares), 转增 (per 10 shares), 派息 (per 10 shares, 元),
    进度 ('实施' | '预案' | ...), 除权除息日, 股权登记日, 红股上市日

We filter to 进度='实施' AND 除权除息日 IS NOT NULL, then map to corp_events:

  event_type  |  ratio formula
  ------------|--------------------------------
   送股       |  送股 / 10         (per-10 → per-1)
   转股       |  转增 / 10
   派息       |  -(派息/10) / ex_close   (need ex_close from daily_raw)

Idempotent via the UNIQUE(code, ex_date, event_type, ratio) constraint. Resumable
via the ``ingest_state`` cursor.

Speed: ~1-2 req/s per worker, 8 workers, 12020 codes ≈ 15-25 min.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from threading import Lock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import akshare as ak
except Exception:
    ak = None

from backend.adapters.market.duckdb_store import (  # noqa: E402
    get_conn,
    init_schema,
    table_stats,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("corp_events_fetcher")

# ---------- ex_close lookup (LRU-ish cache) -------------------------------

_con_lock = Lock()
_con = None
_ex_close_cache: dict = {}


def _get_con():
    global _con
    with _con_lock:
        if _con is None:
            _con = get_conn()
        return _con


def get_ex_close(code: str, ex_date) -> float | None:
    """Look up close on the ex_date from daily_raw. Returns None if missing."""
    key = (code, ex_date)
    if key in _ex_close_cache:
        return _ex_close_cache[key]
    con = _get_con()
    row = con.execute(
        "SELECT close FROM daily_raw WHERE code=? AND trade_date=?",
        [code, ex_date],
    ).fetchone()
    val = float(row[0]) if row else None
    if len(_ex_close_cache) > 100_000:
        _ex_close_cache.pop(next(iter(_ex_close_cache)))
    _ex_close_cache[key] = val
    return val


# ---------- per-stock fetch ----------------------------------------------

def _to_date(v) -> date | None:
    # pd.NaT is a datetime subclass but represents null — must check first.
    try:
        if v is None or pd.isna(v):
            return None
    except (TypeError, ValueError):
        return None
    if isinstance(v, datetime):
        return v.date() if not pd.isna(v) else None
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v).date()
        except ValueError:
            return None
    try:
        ts = pd.to_datetime(v)
        return None if pd.isna(ts) else ts.date()
    except Exception:
        return None


def _to_float(v) -> float:
    if v is None:
        return 0.0
    try:
        x = float(v)
        if pd.isna(x):
            return 0.0
        return x
    except (TypeError, ValueError):
        return 0.0


def fetch_one(code: str) -> tuple[list[dict], str | None]:
    """Fetch all corp_events for one stock. Returns (events, err_msg)."""
    if ak is None:
        return [], "akshare not installed"
    try:
        df = ak.stock_history_dividend_detail(symbol=code, indicator="分红")
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"
    if df is None or len(df) == 0:
        return [], None

    events: list[dict] = []
    for _, r in df.iterrows():
        progress = r.get("进度")
        if progress != "实施":
            continue
        ex_date = _to_date(r.get("除权除息日"))
        if ex_date is None:
            continue
        song = _to_float(r.get("送股"))
        zhuan = _to_float(r.get("转增"))
        pai = _to_float(r.get("派息"))
        if song == 0 and zhuan == 0 and pai == 0:
            continue

        # 送股 + 转股: emit ONE event_type with combined ratio.
        # 派息: separate row, ratio depends on ex_close.
        # If both happen on same day, the cumprod gives the right factor.
        if song + zhuan > 0:
            ratio = (song + zhuan) / 10.0
            events.append({
                "code": code,
                "ex_date": ex_date,
                "event_type": "送股" if song > 0 else "转股",
                "ratio": round(ratio, 8),
                "factor": round(1 + ratio, 10),
                "source": "akshare_sina",
            })
        if pai > 0:
            ex_close = get_ex_close(code, ex_date)
            if ex_close and ex_close > 0:
                ratio = -(pai / 10.0) / ex_close
                events.append({
                    "code": code,
                    "ex_date": ex_date,
                    "event_type": "派息",
                    "ratio": round(ratio, 8),
                    "factor": round(1 + ratio, 10),
                    "source": "akshare_sina",
                })
            # else: skip 派息 — we can't compute factor without ex_close
    return events, None


# ---------- main ---------------------------------------------------------

def _done_codes() -> set[str]:
    """Codes whose last_run ended with 'ok' in ingest_state."""
    con = _get_con()
    rows = con.execute(
        "SELECT code FROM ingest_state "
        "WHERE last_status LIKE 'corp_ok%' "
        "  AND last_trade_date IS NOT NULL"
    ).fetchall()
    return {r[0] for r in rows}


def _mark_done(code: str, n_events: int) -> None:
    con = _get_con()
    # Reuse the existing ingest_state row (PK=code) to track fetcher state too.
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
        (code, f"corp_ok|events={n_events}"),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="Process only first N codes (smoke test).")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-resume", action="store_true",
                    help="Process all codes, ignoring prior progress.")
    args = ap.parse_args()

    if ak is None:
        sys.exit("akshare is not installed in this env")

    init_schema()
    con = _get_con()
    print("SCHEMA state:")
    for t, n in table_stats().items():
        print(f"  {t:20s} {n:>12,d}")
    print()

    # All codes that have a daily_raw row.
    rows = con.execute(
        "SELECT DISTINCT code FROM daily_raw ORDER BY code"
    ).fetchall()
    all_codes = [r[0] for r in rows]
    if not args.no_resume:
        done = _done_codes()
        before = len(all_codes)
        all_codes = [c for c in all_codes if c not in done]
        print(f"resume: {len(done)} already done, {len(all_codes)} remaining "
              f"(of {before} total)")
    if args.limit:
        all_codes = all_codes[:args.limit]
    print(f"plan: {len(all_codes)} stocks, {args.workers} workers")
    print()

    t0 = time.time()
    all_events: list[dict] = []
    err_count = 0
    empty_count = 0
    completed = 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fetch_one, code): code for code in all_codes}
        for fut in as_completed(futures):
            code = futures[fut]
            completed += 1
            try:
                events, err = fut.result()
            except Exception as exc:                           # noqa: BLE001
                err = f"{type(exc).__name__}: {exc}"
                events = []
            if err:
                err_count += 1
                if err_count <= 5:
                    print(f"  ! {code}: {err}", flush=True)
            elif not events:
                empty_count += 1
                _mark_done(code, 0)
            else:
                all_events.extend(events)
                _mark_done(code, len(events))

            if completed % 200 == 0 or completed == len(all_codes):
                elapsed = time.time() - t0
                rate = completed / elapsed if elapsed else 0
                eta = (len(all_codes) - completed) / rate if rate else 0
                print(
                    f"  [{completed:>6d}/{len(all_codes)}] "
                    f"{rate:>5.1f} stk/s  "
                    f"events={len(all_events):>7,}  "
                    f"empty={empty_count:>5,d}  "
                    f"err={err_count:>3d}  "
                    f"ETA {eta:>4.0f}s",
                    flush=True,
                )

    # Bulk insert (idempotent via UNIQUE constraint).
    if all_events:
        # Defensive: drop rows with null ex_date (defence in depth).
        clean = [e for e in all_events if e.get("ex_date") is not None]
        if len(clean) < len(all_events):
            print(f"  dropped {len(all_events) - len(clean)} events with null ex_date")
        df = pd.DataFrame(clean)
        con.register("_corp_staging", df)
        # corp_events.id needs a value; create a sequence if missing.
        con.execute(
            "CREATE SEQUENCE IF NOT EXISTS corp_events_id_seq START 1"
        )
        before = con.execute("SELECT count(*) FROM corp_events").fetchone()[0]
        con.execute("""
            INSERT INTO corp_events (id, code, ex_date, event_type, ratio, factor, source)
            SELECT nextval('corp_events_id_seq'), code, ex_date, event_type,
                   ratio, factor, source
              FROM _corp_staging
            ON CONFLICT (code, ex_date, event_type, ratio) DO NOTHING
        """)
        con.unregister("_corp_staging")
        after = con.execute("SELECT count(*) FROM corp_events").fetchone()[0]
        print(f"\ncorp_events: {before:,} → {after:,}  (+{after - before:,} new)")
    else:
        print("\nno new events to insert")

    print()
    print(f"done in {time.time() - t0:.1f}s")
    print(f"  stocks: {len(all_codes)} (empty: {empty_count}, err: {err_count})")
    print(f"  events fetched: {len(all_events):,}")


if __name__ == "__main__":
    main()
