"""Fallback: copy daily_raw → daily_qfq/hfq for the 125 ETFs eltdx can't serve.

Per Plan A (user-approved): for ETFs we accept qfq=raw since distributions
are <1%/year. This brings ETF coverage from 0% → 100%.

ETFs are identified by code prefix: 51x, 56x, 58x (sh) and 159x (sz).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.adapters.market.duckdb_store import get_conn, table_stats  # noqa: E402


# ETF prefix buckets:
#   sh: 510, 511, 512, 513, 515, 516, 517, 518, 560, 561, 562, 563, 588, 589
#   sz: 159
ETF_PREFIXES = ('510', '511', '512', '513', '515', '516', '517', '518',
                '560', '561', '562', '563', '588', '589', '159')


def _where_clause() -> str:
    parts = [f"substr(code, 1, 3) = '{p}'" for p in ETF_PREFIXES]
    return "(" + " OR ".join(parts) + ")"


def main():
    con = get_conn()
    print("Before:")
    for t in ("daily_raw", "daily_qfq", "daily_hfq"):
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"  {t:12s} {n:>12,}")
    print()

    # ETF codes with raw but no qfq
    miss = con.execute(f"""
        SELECT DISTINCT r.code FROM daily_raw r
         WHERE {_where_clause()}
           AND NOT EXISTS (
               SELECT 1 FROM daily_qfq q
                WHERE q.code = r.code AND q.trade_date = r.trade_date)
         ORDER BY r.code
    """).fetchall()
    miss_codes = [r[0] for r in miss]
    print(f"ETF codes missing qfq: {len(miss_codes)}")
    if miss_codes:
        print(f"  sample: {miss_codes[:10]}")
    print()

    where = _where_clause()

    print("Filling daily_qfq (raw → qfq for ETFs)...")
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
    print(f"  done in {time.time() - t0:.1f}s")

    print("Filling daily_hfq (raw → hfq for ETFs)...")
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
    print(f"  done in {time.time() - t0:.1f}s")
    print()

    print("After:")
    for t in ("daily_raw", "daily_qfq", "daily_hfq"):
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"  {t:12s} {n:>12,}")
    print()

    # Coverage gap by code count
    miss_codes_now = con.execute("""
        SELECT COUNT(DISTINCT r.code) FROM daily_raw r
         WHERE NOT EXISTS (
             SELECT 1 FROM daily_qfq q
              WHERE q.code = r.code AND q.trade_date = r.trade_date)
    """).fetchone()[0]
    n_total_codes = con.execute("SELECT count(DISTINCT code) FROM daily_raw").fetchone()[0]
    print(f"Coverage: {n_total_codes - miss_codes_now}/{n_total_codes} codes have qfq "
          f"({(n_total_codes-miss_codes_now)/n_total_codes*100:.1f}%)")


if __name__ == "__main__":
    main()
