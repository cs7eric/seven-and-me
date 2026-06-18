"""初始化 schema 验证 market_sentiment_index_daily 表存在."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.adapters.market.duckdb_store import init_schema, get_conn

init_schema()
con = get_conn()
# Check market_sentiment_index_daily exists
rows = con.execute(
    "SELECT table_name FROM information_schema.tables "
    "WHERE table_name = 'market_sentiment_index_daily'"
).fetchall()
print("table exists:", len(rows) > 0, rows)

# Show columns
if rows:
    cols = con.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = 'market_sentiment_index_daily' ORDER BY ordinal_position"
    ).fetchall()
    for c in cols:
        print(f"  {c[0]:25s} {c[1]}")
