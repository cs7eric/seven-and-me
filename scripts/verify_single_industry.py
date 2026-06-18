"""验证: 单行业跨日追踪 (get_fund_flow_for_industry + list_industries_with_data)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.adapters.market.duckdb_store import init_schema
init_schema()

from backend.repositories.market.ths_industry_fund_flow_repo import (
    get_fund_flow_for_industry, list_industries_with_data,
)

print("=== list_industries_with_data(days=30) (前 10) ===")
items = list_industries_with_data(days=30)
print(f"total industries with data: {len(items)}")
for it in items[:10]:
    print(f"  {it['industry']:8s} code={it['industryCode']} "
          f"days={it['days']} range={it['firstDate']} -> {it['lastDate']}")

print("\n=== 半导体 近 7 天 ===")
rows = get_fund_flow_for_industry("半导体", days=7)
print(f"count={len(rows)}")
for r in rows:
    print(f"  {r['tradeDate']}: rank={r['rank']} change={r['changePct']}% "
          f"inflow={r['inflow']}亿 outflow={r['outflow']}亿 net={r['net']}亿 "
          f"leader={r['leaderStock']} ({r['leaderChange']}%)")

print("\n=== 银行 近 30 天 (有数据的天) ===")
rows = get_fund_flow_for_industry("银行", days=30)
print(f"count={len(rows)}")
for r in rows:
    print(f"  {r['tradeDate']}: rank={r['rank']} net={r['net']}亿 change={r['changePct']}%")
