"""debug turnover 缺失."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.adapters.market.duckdb_store import get_conn

con = get_conn()

print("=== turnover_activity_daily 最近 10 天 ===")
rows = con.execute("""
    SELECT trade_date, total_amount, avg_20d_amount, ratio, score
    FROM turnover_activity_daily
    ORDER BY trade_date DESC LIMIT 10
""").fetchall()
for r in rows:
    print(f"  {r[0]}  amount={r[1]}  avg={r[2]}  ratio={r[3]}  score={r[4]}")

print("\n=== market_overview_daily 最近 10 天 (total_amount) ===")
rows = con.execute("""
    SELECT trade_date, total_amount
    FROM market_overview_daily
    WHERE total_amount IS NOT NULL
    ORDER BY trade_date DESC LIMIT 10
""").fetchall()
for r in rows:
    print(f"  {r[0]}  total_amount={r[1]}")

print("\n=== coverage ===")
r = con.execute("SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM turnover_activity_daily").fetchone()
print(f"  turnover: {r[0]} ~ {r[1]}  ({r[2]} rows)")
r = con.execute("SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM market_overview_daily WHERE total_amount IS NOT NULL").fetchone()
print(f"  market_overview(total_amount): {r[0]} ~ {r[1]}  ({r[2]} rows)")