"""Verify the fix end-to-end: limit_emotion + market_sentiment composite."""
import sys
sys.path.insert(0, ".")

from backend.adapters.market.duckdb_store import get_conn

con = get_conn()

print("=" * 100)
print("limit_emotion_summary_daily (recent 12 days)")
print("=" * 100)
print(f'{"date":<12} {"up":>5} {"down":>5} {"ratio":>8} {"upDown":>7} {"bb":>7} {"yest":>7} {"comp":>7}  {"level"}')
rows = con.execute("""
    SELECT trade_date, limit_up_count, limit_down_count, up_down_score,
           break_board_score, yesterday_return_score, composite_score, level
      FROM limit_emotion_summary_daily
     ORDER BY trade_date DESC LIMIT 12
""").fetchall()
for r in rows:
    ratio = r[1] / max(r[2], 1)
    print(
        f'{r[0].isoformat():<12} {r[1]:>5} {r[2]:>5} {ratio:>8.2f} '
        f'{float(r[3]):>7.2f} {float(r[4]):>7.2f} {float(r[5]):>7.2f} '
        f'{float(r[6]):>7.2f}  {r[7]}'
    )

print()
print("=" * 100)
print("limit_down_count distribution (should NOT be all 0 anymore)")
print("=" * 100)
rows = con.execute("""
    SELECT limit_down_count, COUNT(*) AS days
      FROM limit_emotion_summary_daily
     GROUP BY limit_down_count
     ORDER BY limit_down_count
""").fetchall()
for r in rows:
    print(f"  down_count={r[0]:>4}  days={r[1]}")

print()
print("=" * 100)
print("up_down_score distribution (should NOT be all 100 anymore)")
print("=" * 100)
rows = con.execute("""
    SELECT
      CASE
        WHEN up_down_score = 100 THEN '=100 (saturated)'
        WHEN up_down_score >= 75 THEN '75-99 (hot)'
        WHEN up_down_score >= 50 THEN '50-74 (warm)'
        WHEN up_down_score >= 25 THEN '25-49 (cool)'
        ELSE '0-24 (cold)'
      END AS bucket,
      COUNT(*) AS days
    FROM limit_emotion_summary_daily
    GROUP BY bucket
    ORDER BY bucket
""").fetchall()
for r in rows:
    print(f"  {r[0]:<25} days={r[1]}")

print()
print("=" * 100)
print("market_sentiment_index_daily recent 10d (limit_emotion component shift visible)")
print("=" * 100)
print(f'{"date":<12} {"limit_em":>8} {"composite":>9} {"level":<10} {"before-composite":<16}')
# before fix: market_sentiment_index_daily stored values — we don't have them anymore, but we can show new vs old-style
# Just show the updated stored values
rows = con.execute("""
    SELECT trade_date, limit_emotion_score, composite_score, level
      FROM market_sentiment_index_daily
     WHERE limit_emotion_score IS NOT NULL
     ORDER BY trade_date DESC LIMIT 12
""").fetchall()
for r in rows:
    print(
        f'{r[0].isoformat():<12} {float(r[1]):>8.2f} {float(r[2]):>9.2f}  {r[3]}'
    )