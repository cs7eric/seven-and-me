import json
with open("reference/stock-universe/sectors/sectors_industries_0.json", encoding="utf-8") as f:
    data = json.load(f)
sectors = data.get("sectors", [])
print("industries count:", len(sectors))
total = sum(s.get("stock_count", 0) for s in sectors)
print("total stocks in industries (sum):", total)
for s in sectors[:15]:
    print(f"  {s['name']:20s} stocks={s['stock_count']:4d}  sample={s.get('stock_codes', [])[:3]}")
