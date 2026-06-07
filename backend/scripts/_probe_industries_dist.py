"""分析 sectors_industries_0.json 3040 个 sector 是不是真行业."""
import json, re

with open("reference/stock-universe/sectors/sectors_industries_0.json", encoding="utf-8") as f:
    data = json.load(f)
sectors = data.get("sectors", [])

print(f"industries_0 总数: {len(sectors)}")
print()

# 按 stock_count 分布
from collections import Counter
cnt = Counter(s.get("stock_count", 0) for s in sectors)
print("stock_count 分布:")
for n in sorted(cnt.keys())[:15]:
    print(f"  count={n:4d}  sectors={cnt[n]}")
print()

# 看起来"真行业"的特征: stock_count 比较大 (>= 5), 不含 "业务"/"主营"/"产品"/"研发"
suspicious_pat = re.compile(r"业务|主营|产品|研发|服务|设计|销售|生产|经营|管理|咨询")
clean = 0
dirty = 0
no_tid_clean = 0
no_tid_dirty = 0
samples = []
for s in sectors:
    name = s.get("name", "")
    sc = s.get("stock_count", 0)
    tid = s.get("topic_id")
    is_dirty = bool(suspicious_pat.search(name)) or sc <= 2
    if is_dirty:
        dirty += 1
        if not tid:
            no_tid_dirty += 1
    else:
        clean += 1
        if not tid:
            no_tid_clean += 1
    if sc == 1 and len(samples) < 10:
        samples.append((sc, name, tid))

print(f"看起来是真行业 (stock_count>=3 且名不含业务/主营/产品/研发): {clean}")
print(f"看起来是脏数据 (业务/主营/产品/研发 或 stock_count<=2): {dirty}")
print()
print(f"脏数据里没 topic_id 的: {no_tid_dirty}")
print(f"真行业里没 topic_id 的: {no_tid_clean}")
print()
print("stock_count=1 抽样 (10 个):")
for sc, n, t in samples:
    print(f"  count={sc} tid={t} name={n}")
