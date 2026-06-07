import json
files = [
    "reference/stock-universe/sectors/sectors_industries_0.json",
    "reference/stock-universe/sectors/sectors_concepts_2.json",
    "reference/stock-universe/sectors/sectors_styles_4.json",
]
for f in files:
    with open(f, encoding="utf-8") as fp:
        data = json.load(fp)
    for s in data.get("sectors", []):
        # sector 字段看 key 都叫什么
        keys = list(s.keys())
        # print one sample to see schema
        break
    print(f"{f.split('/')[-1]}: sector schema = {data.get('sectors', [{}])[0].keys() if data.get('sectors') else None}")
    print()

# 现在找 881289 / 881087
print("=== 找 881289 / 881087 ===")
for f in files:
    with open(f, encoding="utf-8") as fp:
        data = json.load(fp)
    for s in data.get("sectors", []):
        all_str = json.dumps(s, ensure_ascii=False)
        if "881289" in all_str or "881087" in all_str:
            print(f"  {f.split('/')[-1]}: {s}")
