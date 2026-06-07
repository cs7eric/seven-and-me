import json
files = [
    "reference/stock-universe/sectors/sectors_industries_0.json",
    "reference/stock-universe/sectors/sectors_concepts_2.json",
    "reference/stock-universe/sectors/sectors_styles_4.json",
]
keywords = ["智能制造", "智能制造装备", "晶圆测试", "探针卡", "汽车制造", "机器视觉", "智能机器", "工业4.0"]
for f in files:
    with open(f, encoding="utf-8") as fp:
        data = json.load(fp)
    for s in data.get("sectors", []):
        for k in keywords:
            if k in s.get("name", ""):
                tid = s.get("topic_id")
                print(f"  {f.split('/')[-1]:40s} {s['name']:20s} stocks={s['stock_count']:4d} topic_id={tid}")
                break
