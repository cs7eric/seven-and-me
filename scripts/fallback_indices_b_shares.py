"""Fallback: copy raw → qfq/hfq for indices and B-shares.

These have no corp events (indices are calculated; B-shares we'll skip per
user decision), so qfq == raw. This eliminates ~3.5M rows from the gap.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.adapters.market.duckdb_store import get_conn, table_stats  # noqa: E402

# Code prefix buckets that don't need复权:
#  880, 881, 882, 887, 888   — TDX sector/industry indices (申万/同花顺)
#  395                       — 中证 custom series
#  399                       — 深证指数 series
#  200, 900                  — B-shares (per user decision, skip)
SKIP_PREFIXES = (
    ("200", 3),    # 深B
    ("900", 3),    # 沪B
    ("395", 3),    # 中证
    ("399", 3),    # 深证指数
    ("880", 3),    # 申万一级
    ("881", 3),    # 同花顺概念
    ("882", 3),    # 申万二级
    ("887", 3),
    ("888", 3),
)


def _where_clause() -> str:
    parts = [f"substr(code, 1, {n}) = '{p}'" for p, n in SKIP_PREFIXES]
    return "(" + " OR ".join(parts) + ")"


def main():
    con = get_conn()
    print("Before:")
    for t in ("daily_raw", "daily_qfq", "daily_hfq"):
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"  {t:12s} {n:>12,}")
    print()

    where = _where_clause()

    print("Filling daily_qfq (raw → qfq for indices/B-shares)...")
    t0 = time.time()
    con.execute(f"""
        INSERT INTO daily_qfq (code, trade_date, open, high, low, close,
                               volume, amount, adj_factor, ingested_at)
        SELECT r.code, r.trade_date, r.open, r.high, r.low, r.close,
               r.volume, r.amount, 1.0, current_timestamp
          FROM daily_raw r
         WHERE {where}
           AND NOT EXISTS (
               SELECT 1 FROM daily_qfq q
                WHERE q.code = r.code AND q.trade_date = r.trade_date
           )
    """)
    n = con.execute(f"""
        SELECT count(*) FROM daily_qfq
         WHERE {_where_clause()}
    """).fetchone()[0]
    print(f"  done in {time.time() - t0:.1f}s, daily_qfq rows for skip-prefixes: {n:,}")

    print("Filling daily_hfq (raw → hfq for indices/B-shares)...")
    t0 = time.time()
    con.execute(f"""
        INSERT INTO daily_hfq (code, trade_date, open, high, low, close,
                               volume, amount, adj_factor, ingested_at)
        SELECT r.code, r.trade_date, r.open, r.high, r.low, r.close,
               r.volume, r.amount, 1.0, current_timestamp
          FROM daily_raw r
         WHERE {where}
           AND NOT EXISTS (
               SELECT 1 FROM daily_hfq h
                WHERE h.code = r.code AND h.trade_date = r.trade_date
           )
    """)
    n = con.execute(f"""
        SELECT count(*) FROM daily_hfq
         WHERE {_where_clause()}
    """).fetchone()[0]
    print(f"  done in {time.time() - t0:.1f}s, daily_hfq rows for skip-prefixes: {n:,}")
    print()

    print("After:")
    for t in ("daily_raw", "daily_qfq", "daily_hfq"):
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"  {t:12s} {n:>12,}")
    print()

    # Coverage gap now
    missing = con.execute("""
        SELECT count(*) FROM daily_raw r
         WHERE NOT EXISTS (
             SELECT 1 FROM daily_qfq q
              WHERE q.code = r.code AND q.trade_date = r.trade_date)
    """).fetchone()[0]
    print(f"Remaining qfq gap (A-shares/ETFs): {missing:,} rows")


if __name__ == "__main__":
    main()