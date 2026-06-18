"""验证 backfill 结果."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.adapters.market.duckdb_store import get_conn

con = get_conn()

# 总览
r = con.execute(
    "SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM market_sentiment_index_daily"
).fetchone()
print(f"coverage: {r[0]} ~ {r[1]}  ({r[2]} rows)")

# 5 天样本 (含 component_count)
print("\n=== last 5 days ===")
rows = con.execute("""
    SELECT trade_date, composite_score, level, component_count,
           vol_score, turnover_score, breadth_score, limit_emotion_score,
           price_strength_score, risk_appetite_score, profit_effect_score,
           sector_breadth_score, style_risk_score
    FROM market_sentiment_index_daily
    ORDER BY trade_date DESC LIMIT 5
""").fetchall()
for r in rows:
    def fmt(v):
        return f"{v:>5.1f}" if v is not None else "   —"
    print(f"{r[0]}  composite={r[1]:.2f}  level={r[2]:8s}  cnt={r[3]}/9")
    print(f"  vol={fmt(r[4])}  turnover={fmt(r[5])}  breadth={fmt(r[6])}  limit={fmt(r[7])}")
    print(f"  price={fmt(r[8])}  risk_app={fmt(r[9])}  profit={fmt(r[10])}  sector={fmt(r[11])}  style={fmt(r[12])}")

# 等级分布
print("\n=== level distribution ===")
rows = con.execute("""
    SELECT level, COUNT(*) FROM market_sentiment_index_daily
    GROUP BY level ORDER BY level
""").fetchall()
for r in rows:
    print(f"  {r[0]:8s}  {r[1]}")

# 最近 component_count 分布
print("\n=== component_count distribution ===")
rows = con.execute("""
    SELECT component_count, COUNT(*) FROM market_sentiment_index_daily
    GROUP BY component_count ORDER BY component_count
""").fetchall()
for r in rows:
    print(f"  {r[0]}/9  {r[1]} days")
