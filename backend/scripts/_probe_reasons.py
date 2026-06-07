"""分析 topics.reason 各种格式的占比."""
import sys, re
sys.path.insert(0, ".")
from collections import Counter
from backend.services.stock.stock_universe_service import load_latest, extract_industry_from_reason

uni = load_latest()
stocks = uni.get("stocks") or []

# 收集所有 reason 文本，按首 20 字分类
patterns = Counter()
empty_ind_stocks = 0
for s in stocks:
    if s.get("industry"):
        continue
    empty_ind_stocks += 1
    seen_pat = False
    for t in s.get("topics") or []:
        reason = t.get("reason") or ""
        if not reason or seen_pat:
            continue
        # 取前 12 字
        prefix = reason[:12]
        patterns[prefix] += 1
        seen_pat = True
        break

print(f"universe 中 industry 为空的: {empty_ind_stocks} / {len(stocks)}")
print()
print("Top 20 reason 前缀:")
for p, c in patterns.most_common(20):
    print(f"  {c:4d}  {p}")

# 测一个更广的正则
EXTRA_RE_LIST = [
    r"([一-龥]{2,12})(?:制造|加工|生产|销售|服务|研发|开发|设计|经营|提供)",
    r"([一-龥]{2,8})行业",
    r"([一-龥]{2,8})业[是为]",
]
extra = 0
for s in stocks:
    if s.get("industry"):
        continue
    for t in s.get("topics") or []:
        reason = t.get("reason") or ""
        if not reason:
            continue
        for pat in EXTRA_RE_LIST:
            m = re.search(pat, reason)
            if m:
                name = m.group(1)
                if name not in {"研发", "生产", "销售", "服务", "公司", "主营", "业务"} and len(name) >= 2:
                    extra += 1
                break
        break
print(f"\n用更广的 (X制造/X行业/X业) 启发式可多覆盖: {extra} 只")
