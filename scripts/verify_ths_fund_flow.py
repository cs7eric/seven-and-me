"""最终验证: ths_industry_fund_flow_daily 全链路."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.adapters.market.duckdb_store import init_schema
from backend.repositories.market.ths_industry_fund_flow_repo import (
    coverage, get_fund_flow_daily_topn, get_fund_flow_history,
)

init_schema()
print("=== coverage ===")
print(json.dumps(coverage(), indent=2, ensure_ascii=False))

print("\n=== get_fund_flow_daily_topn(2026-06-15, top_n=3) ===")
out = get_fund_flow_daily_topn("2026-06-15", top_n=3)
print(json.dumps(out, indent=2, ensure_ascii=False)[:800])

print("\n=== get_fund_flow_history(days=7, topN=2) ===")
hist = get_fund_flow_history(days=7, top_n=2)
print(f"count={len(hist)}, first day items={len(hist[0]['items']) if hist else 0}, "
      f"last day items={len(hist[-1]['items']) if hist else 0}")

print("\n=== sample: 半导体 跨 7 天 ===")
for day in hist:
    items = day["items"]
    semi = next((x for x in items if x["industry"] == "半导体"), None)
    if semi:
        print(f"  {day['tradeDate']}: change={semi['changePct']}%, net={semi['net']}亿, "
              f"inflow={semi['inflow']}亿, leader={semi['leaderStock']} ({semi['leaderChange']}%)")
