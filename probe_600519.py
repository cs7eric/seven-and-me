"""检查 sectors.json 里 sh600519 的归一."""
import json
data = json.load(open("reference/stock-universe/sectors.json", encoding="utf-8"))

# 1) 行业包含 "白酒"
print("--- industries named 白酒 ---")
for ind in data["industries"]:
    if "白酒" in ind["name"]:
        print(f"  {ind['name']:<10} stock_count={ind['stock_count']}")
        print(f"    sample codes: {ind['stock_codes'][:8]}")

# 2) 找 code == sh600519
print()
print("--- search 'sh600519' in all industries ---")
for ind in data["industries"]:
    if "sh600519" in ind["stock_codes"]:
        print(f"  found in industry: {ind['name']}")

# 3) 找 sh600519 的题材
print()
print("--- search 'sh600519' in all topics (top 30) ---")
hits = [t for t in data["topics"] if "sh600519" in t["stock_codes"]]
print(f"  total: {len(hits)}")
for t in hits[:10]:
    print(f"  {t['topic_name']:<20} topic_id={t['topic_id']}")
