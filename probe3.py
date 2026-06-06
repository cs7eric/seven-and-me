import json
import sys
sys.path.insert(0, ".")
from backend.services.stock.market_heatmap_service import build_market_heatmap

data = build_market_heatmap()
print(f"ok={data.get('ok')}, items={len(data.get('items') or [])}, totalStocks={data.get('totalStocks')}")
items = data.get("items") or []
for s in items[:3]:
    print(f"  {s['name']:<8} value={s.get('value'):.2f} children={len(s.get('children') or [])}")
    for c in s.get("children", [])[:3]:
        print(f"    {c['name']:<8} code={c['code']} value={c.get('amount', 0):.2f}")
