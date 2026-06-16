"""Smoke test: write/read/upsert on daily_raw."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from datetime import date
from backend.adapters.market.duckdb_store import conn

sample = [
    ('302132', date(2026, 6, 9),  57.26, 57.59, 56.36, 56.91, 6701269,  381825920, 10, 'tdx_day'),
    ('302132', date(2026, 6, 10), 56.92, 57.97, 56.40, 56.68, 6082385,  346956192, 10, 'tdx_day'),
    ('302132', date(2026, 6, 11), 56.03, 58.13, 55.44, 57.60, 9870468,  565064960, 10, 'tdx_day'),
    ('302132', date(2026, 6, 12), 58.00, 64.30, 57.99, 63.81, 22281812, 1396142336, 10, 'tdx_day'),
    ('302132', date(2026, 6, 15), 61.68, 61.80, 60.38, 61.35, 14590162, 891966336,  10, 'tdx_day'),
]

with conn() as c:
    c.executemany(
        'INSERT INTO daily_raw VALUES (?,?,?,?,?,?,?,?,?,?,current_timestamp)',
        sample,
    )
    c.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES ('smoke_test','passed')")

    rows = c.execute(
        "SELECT trade_date, open, close, volume FROM daily_raw "
        "WHERE code = ? ORDER BY trade_date", ['302132']
    ).fetchall()
    print("--- daily_raw for 302132 ---")
    for r in rows:
        print(f"  {r[0]}  o={r[1]:>6.2f}  c={r[2]:>6.2f}  v={r[3]:>10d}")
    print()
    print("--- schema_meta ---")
    for r in c.execute("SELECT key, value FROM schema_meta").fetchall():
        print(f"  {r[0]:15s} = {r[1]}")

    # upsert test (PK conflict -> replace)
    c.execute(
        "INSERT OR REPLACE INTO daily_raw VALUES "
        "('302132', '2026-06-15', 99.99, 99.99, 99.99, 99.99, 0, 0, 10, 'tencent', current_timestamp)"
    )
    n = c.execute("SELECT count(*) FROM daily_raw WHERE code = '302132'").fetchone()[0]
    print(f"\nrow count after upsert on 2026-06-15: {n} (should still be 5)")

    # cleanup
    c.execute("DELETE FROM daily_raw WHERE code = '302132'")
    c.execute("DELETE FROM schema_meta WHERE key = 'smoke_test'")
    print("cleaned up test rows")
