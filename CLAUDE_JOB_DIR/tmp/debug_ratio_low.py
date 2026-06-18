"""看 turnover ratio 分布."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.adapters.market.duckdb_store import get_conn

con = get_conn()

# ratio 分布
print("=== ratio 最低 10 天 ===")
rows = con.execute("""
    SELECT trade_date, ratio, score, total_amount, avg_20d_amount
    FROM turnover_activity_daily
    ORDER BY ratio ASC LIMIT 10
""").fetchall()
for r in rows:
    print(f"  {r[0]}  ratio={r[1]:.4f}  score={r[2]:>5}  total={r[3]:.0f}  avg20={r[4]:.0f}")

print("\n=== ratio 最高 10 天 ===")
rows = con.execute("""
    SELECT trade_date, ratio, score, total_amount, avg_20d_amount
    FROM turnover_activity_daily
    ORDER BY ratio DESC LIMIT 10
""").fetchall()
for r in rows:
    print(f"  {r[0]}  ratio={r[1]:.4f}  score={r[2]:>5}  total={r[3]:.0f}  avg20={r[4]:.0f}")

# score=0 的有多少天
print("\n=== score == 0 的天数 ===")
r = con.execute("SELECT COUNT(*) FROM turnover_activity_daily WHERE score = 0").fetchone()
print(f"  score=0: {r[0]} days")
r = con.execute("SELECT COUNT(*) FROM turnover_activity_daily WHERE score IS NULL").fetchone()
print(f"  score=NULL: {r[0]} days")

# 2026-06-18 当天的 total_amount 是什么
print("\n=== 2026-06-18 附近 total_amount 走势 ===")
rows = con.execute("""
    SELECT trade_date, total_amount, avg_20d_amount, ratio
    FROM turnover_activity_daily
    WHERE trade_date BETWEEN '2026-06-10' AND '2026-06-18'
    ORDER BY trade_date
""").fetchall()
for r in rows:
    print(f"  {r[0]}  total={r[1]:>10.0f}  avg20={r[2]:>10.0f}  ratio={r[3]:.4f}")