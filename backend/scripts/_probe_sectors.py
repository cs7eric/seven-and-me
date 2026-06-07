import json
files = [
    "reference/stock-universe/sectors/sectors_industries_0.json",
    "reference/stock-universe/sectors/sectors_concepts_2.json",
    "reference/stock-universe/sectors/sectors_styles_4.json",
]
for f in files:
    with open(f, encoding="utf-8") as fp:
        data = json.load(fp)
    sectors = data.get("sectors", [])
    with_tid = sum(1 for s in sectors if s.get("topic_id"))
    no_tid = sum(1 for s in sectors if not s.get("topic_id"))
    total_codes = sum(len(s.get("stock_codes", [])) for s in sectors)
    print(f"{f.split('/')[-1]}:")
    print(f"  total sectors: {len(sectors)}")
    print(f"  with topic_id: {with_tid}    no topic_id: {no_tid}")
    print(f"  total codes (sum, with dup): {total_codes}")
    print(f"  top 5 by stock_count:")
    for s in sorted(sectors, key=lambda x: -x.get("stock_count", 0))[:5]:
        tid = s.get("topic_id", "None")
        print(f"    {s['name']:20s} stocks={s['stock_count']:4d}  topic_id={tid}")
    print()
