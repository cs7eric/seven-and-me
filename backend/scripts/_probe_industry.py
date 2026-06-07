import sys
sys.path.insert(0, ".")
from backend.services.stock.stock_universe_service import load_latest

uni = load_latest()
stocks = uni.get("stocks") or []
has_ind = sum(1 for s in stocks if s.get("industry"))
print(f"industry 覆盖率: {has_ind} / {len(stocks)}  ({has_ind/len(stocks)*100:.1f}%)")
print()

# category_raw=0 的 topic 是行业归一 (eltdx 题材里 cat=0 是行业)
def cat0_topics(s):
    return [t["topic_name"] for t in s.get("topics", []) if t.get("category_raw") == 0]

# 抽 5 只有 industry 的
print("=== 有 industry 的样例 ===")
for s in stocks:
    if s.get("industry"):
        print(f"  {s['code']:10s} {s.get('name',''):6s}  industry={s['industry']:20s}  cat0_topics={cat0_topics(s)[:3]}")
        break

# 抽 5 个没 industry 的，看 cat0_topics 是否有可用
print()
print("=== 没 industry 的样例 (前 5) ===")
seen = 0
for s in stocks:
    if not s.get("industry"):
        ct = cat0_topics(s)
        print(f"  {s['code']:10s} {s.get('name',''):6s}  cat0_topics={ct[:3]}")
        seen += 1
        if seen >= 5:
            break

# 行业字段来源统计
print()
print("=== 抽 30 只的 industry 字段来源 ===")
for s in stocks[:30]:
    ct = cat0_topics(s)
    print(f"  {s['code']:10s} ind={s.get('industry','(空)'):20s}  cat0={ct[:2]}")
