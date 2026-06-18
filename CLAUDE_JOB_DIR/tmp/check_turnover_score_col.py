"""验证 turnover_activity_daily.score 列是否存在."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.adapters.market.duckdb_store import get_conn

con = get_conn()
cols = con.execute(
    "SELECT column_name, data_type FROM information_schema.columns "
    "WHERE table_name = 'turnover_activity_daily' ORDER BY ordinal_position"
).fetchall()
for c in cols:
    print(f"  {c[0]:25s} {c[1]}")

# 行数 + score 为 NULL 的天数
r = con.execute("""
    SELECT COUNT(*) AS total,
           COUNT(score) AS with_score,
           COUNT(*) - COUNT(score) AS null_score
    FROM turnover_activity_daily
""").fetchone()
print(f"\nturnover_activity_daily: total={r[0]}  with_score={r[1]}  null_score={r[2]}")