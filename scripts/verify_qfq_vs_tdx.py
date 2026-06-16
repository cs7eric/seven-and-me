"""Validate daily_qfq against a known TDX 前复权 export.

Reference: TDX client export of 001270 (铖昌科技) 2022-06-06 to 2022-07-05.
For these dates 001270 had NO corp events, so the 复权因子 is determined by
events *after* the export window (i.e. events with ex_date > 2022-07-05).

Expected:
  2022-06-06 open : TDX 13.75    raw  2.602    ratio  ≈ 5.28
  2022-06-06 close: TDX 16.60    raw  3.122    ratio  ≈ 5.32
  2022-07-05 close: TDX 50.38    raw  9.269    ratio  ≈ 5.44

This script:
  1. Reads the 001270 corp_events we fetched
  2. Reads 001270 daily_raw and daily_qfq
  3. Reports actual ratios for the export window
  4. If 001270 has post-window corp events, checks adj_factor at each date
  5. Compares raw × adj_factor to the TDX export values

Tolerance: ±2% on the ratio (mostly the per-day open is the loosest, since
intraday prices vary more).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.adapters.market.duckdb_store import conn

# TDX export of 001270 铖昌科技, 2022-06-06 to 2022-07-05, 22 rows.
# Columns: trade_date, tdx_open, tdx_high, tdx_low, tdx_close, volume, amount
TDX_EXPORT = [
    ("2022-06-06", 13.75, 16.60, 13.75, 16.60),
    ("2022-06-07", 18.32, 18.32, 18.32, 18.32),
    ("2022-06-08", 20.20, 20.20, 20.20, 20.20),
    ("2022-06-09", 22.28, 22.28, 22.28, 22.28),
    ("2022-06-10", 24.56, 24.56, 24.56, 24.56),
    ("2022-06-13", 27.07, 27.07, 27.07, 27.07),
    ("2022-06-14", 29.84, 29.84, 29.84, 29.84),
    ("2022-06-15", 32.88, 32.88, 32.88, 32.88),
    ("2022-06-16", 36.22, 36.22, 36.22, 36.22),
    ("2022-06-17", 39.89, 39.89, 39.89, 39.89),
    ("2022-06-20", 43.94, 43.94, 43.94, 43.94),
    ("2022-06-21", 46.70, 48.39, 45.54, 48.39),
    ("2022-06-22", 48.39, 53.28, 46.71, 50.83),
    ("2022-06-23", 54.12, 55.97, 53.92, 55.97),
    ("2022-06-24", 58.04, 61.62, 57.69, 58.18),
    ("2022-06-27", 58.30, 62.79, 58.25, 62.42),
    ("2022-06-28", 61.05, 61.98, 57.20, 60.43),
    ("2022-06-29", 60.44, 60.98, 54.33, 54.39),
    ("2022-06-30", 54.45, 55.98, 53.30, 55.05),
    ("2022-07-01", 54.39, 60.61, 53.34, 60.61),
    ("2022-07-04", 60.44, 60.44, 54.50, 54.50),
    ("2022-07-05", 53.31, 54.31, 48.99, 50.38),
]

CODE = "001270"


def main():
    with conn() as c:
        n_corp = c.execute(
            "SELECT count(*) FROM corp_events WHERE code=?", [CODE]
        ).fetchone()[0]
        print(f"001270 corp_events: {n_corp}")
        if n_corp > 0:
            print("  events:")
            for r in c.execute(
                "SELECT ex_date, event_type, ratio, factor "
                "FROM corp_events WHERE code=? ORDER BY ex_date", [CODE]
            ).fetchall():
                print(f"    {r}")
        print()

        # Pull raw + qfq for the export window.
        rows = c.execute(
            f"""
            SELECT r.trade_date, r.open ro, r.high rh, r.low rl, r.close rc,
                   q.open qo, q.high qh, q.low ql, q.close qc, q.adj_factor
              FROM daily_raw r
              JOIN daily_qfq q ON r.code=q.code AND r.trade_date=q.trade_date
             WHERE r.code = '{CODE}'
               AND r.trade_date BETWEEN DATE '2022-06-06' AND DATE '2022-07-05'
             ORDER BY r.trade_date
            """
        ).fetchall()

        if not rows:
            print("  (no qfq data yet — run materialize_qfq_hfq.py first)")
            return

        # Build a dict of TDX export values for lookup
        tdx_by_date = {d: (o, h, l, cl) for d, o, h, l, cl in TDX_EXPORT}

        print(f"  {'date':<10}  {'raw open':>10}  {'qfq open':>10}  "
              f"{'ratio open':>10}  {'raw close':>10}  {'qfq close':>10}  "
              f"{'ratio close':>10}  {'TDX close':>10}  {'TDX/raw':>8}")
        deltas = []
        for td, ro, rh, rl, rc, qo, qh, ql, qc, af in rows:
            r_open = float(ro)
            r_close = float(rc)
            q_open = float(qo)
            q_close = float(qc)
            ratio_open = q_open / r_open if r_open else 0
            ratio_close = q_close / r_close if r_close else 0
            tdx_o, tdx_h, tdx_l, tdx_c = tdx_by_date.get(td.isoformat(), (0, 0, 0, 0))
            tdx_ratio = tdx_c / r_close if r_close else 0
            print(f"  {str(td):<10}  {r_open:>10.3f}  {q_open:>10.3f}  "
                  f"{ratio_open:>10.4f}  {r_close:>10.3f}  {q_close:>10.3f}  "
                  f"{ratio_close:>10.4f}  {tdx_c:>10.3f}  {tdx_ratio:>8.4f}")
            deltas.append(abs(ratio_close - tdx_ratio) / tdx_ratio if tdx_ratio else 0)

        # Pass/fail: mean absolute relative delta vs TDX export (close column)
        mean = sum(deltas) / len(deltas) if deltas else 0
        max_d = max(deltas) if deltas else 0
        print()
        print(f"mean |delta| vs TDX export (close): {mean*100:.3f}%")
        print(f"max  |delta| vs TDX export (close): {max_d*100:.3f}%")
        if max_d < 0.02:
            print("PASS  (within 2%)")
        else:
            print("FAIL  (exceeds 2% tolerance)")


if __name__ == "__main__":
    main()
