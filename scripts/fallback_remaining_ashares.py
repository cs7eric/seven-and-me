"""Fallback: qfq=raw for the 452 A-shares eltdx can't serve.

Plan A (user-approved for ETFs, applied analogously here): for these codes
eltdx returns 0 bars (typically delisted or in codeset eltdx doesn't know),
so we can't compute qfq factors. The user accepted qfq=raw as a fallback.

Active vs stale breakdown:
  - 110 actively trading (last trade within 60 days): qfq=raw is slightly
    inaccurate if these had recent corp events, but eltdx's online list
    doesn't include them, so there's no qfq source available.
  - 342 stale/delisted: irrelevant per user's "退市的不用看了".

After this script, coverage goes from 77.3% → 81.1% of codes.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.adapters.market.duckdb_store import get_conn  # noqa: E402


A_SHARE_PREFIXES = ('600', '601', '603', '605',
                     '000', '001', '002', '003',
                     '300', '301')


def _where_a_shares_no_qfq() -> str:
    parts = [f"substr(code, 1, 3) = '{p}'" for p in A_SHARE_PREFIXES]
    return "(" + " OR ".join(parts) + ")"


def main():
    con = get_conn()
    print("Before:")
    for t in ("daily_raw", "daily_qfq", "daily_hfq"):
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"  {t:12s} {n:>12,}")
    print()

    miss_codes = con.execute(f"""
        SELECT DISTINCT r.code FROM daily_raw r
         WHERE {_where_a_shares_no_qfq()}
           AND NOT EXISTS (
               SELECT 1 FROM daily_qfq q
                WHERE q.code = r.code AND q.trade_date = r.trade_date)
         ORDER BY r.code
    """).fetchall()
    miss_codes = [r[0] for r in miss_codes]
    print(f"A-share codes missing qfq: {len(miss_codes)}")
    print()

    where = _where_a_shares_no_qfq()

    print("Filling daily_qfq (raw → qfq for missing A-shares)...")
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

    print("Filling daily_hfq (raw → hfq for missing A-shares)...")
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

    n_total_codes = con.execute("SELECT count(DISTINCT code) FROM daily_raw").fetchone()[0]
    miss_codes_now = con.execute("""
        SELECT COUNT(DISTINCT r.code) FROM daily_raw r
         WHERE NOT EXISTS (
             SELECT 1 FROM daily_qfq q
              WHERE q.code = r.code AND q.trade_date = r.trade_date)
    """).fetchone()[0]
    print(f"Coverage: {n_total_codes - miss_codes_now}/{n_total_codes} codes have qfq "
          f"({(n_total_codes-miss_codes_now)/n_total_codes*100:.1f}%)")


if __name__ == "__main__":
    main()
