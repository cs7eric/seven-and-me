"""验证 industry_code enrich."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.adapters.market.duckdb_store import init_schema
init_schema()

from backend.repositories.market.ths_industry_fund_flow_repo import (
    get_fund_flow_daily, list_industries_with_data,
)

print("=== 2026-06-15 前 5 行 (看 industryCode) ===")
rows = get_fund_flow_daily("2026-06-15")
for r in rows[:5]:
    code = r["industryCode"] or "None"
    print(f"  rank={r['rank']:>3d} {r['industry']:8s} code={code:8s} "
          f"change={r['changePct']:>6.2f}% net={r['net']:>8.2f}亿")

print()
print("=== list_industries_with_data(days=30) 覆盖率 ===")
items = list_industries_with_data(days=30)
total = len(items)
with_code = sum(1 for it in items if it["industryCode"])
pct = (with_code * 100 // total) if total else 0
print(f"  total={total}, industryCode 非空={with_code} ({pct}%)")
print()
print("前 10 个示例:")
for it in items[:10]:
    print(f"  {it['industry']:8s} code={it['industryCode']} days={it['days']}")

print()
print("=== 半导体 跨 7 天 (看 industryCode 是否一致) ===")
from backend.repositories.market.ths_industry_fund_flow_repo import get_fund_flow_for_industry
semi = get_fund_flow_for_industry("半导体", days=7)
for r in semi:
    print(f"  {r['tradeDate']}: code={r['industryCode']} net={r['net']}亿 "
          f"change={r['changePct']}% leader={r['leaderStock']}")
