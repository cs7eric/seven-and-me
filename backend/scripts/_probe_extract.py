"""验证扩充后的 extract_industry_from_reason 的命中率."""
import sys
sys.path.insert(0, ".")
import re
from backend.services.stock.stock_universe_service import load_latest, extract_industry_from_reason

uni = load_latest()
stocks = uni.get("stocks") or []

# 1. 用旧 industry 字段做 baseline
baseline = sum(1 for s in stocks if s.get("industry"))
print(f"baseline (universe 已有 industry): {baseline} / {len(stocks)}  ({baseline/len(stocks)*100:.1f}%)")

# 2. 对 industry 为空 或者 看起来是 reason 文本 的 stock, 用新正则从 topics 重新 extract
fixable = 0
new_ind = 0
samples = []
for s in stocks:
    ind = s.get("industry") or ""
    topics = s.get("topics") or []
    for t in topics:
        reason = t.get("reason") or ""
        extracted = extract_industry_from_reason(reason)
        if extracted and (not ind or len(ind) > 16):
            new_ind += 1
            if len(samples) < 10:
                samples.append((s["code"], ind or "(空)", extracted, reason[:40]))
            break

print(f"用新正则从 topics.reason 重新 extract: {new_ind} 只可修复")
print()
for code, old, new, reason in samples:
    print(f"  {code:10s} old=[{old[:20]}] new=[{new}] reason={reason}")

# 3. 整体看: 哪些 code 完全没有任何 industry 线索
still_empty = 0
for s in stocks:
    if s.get("industry"):
        continue
    found = False
    for t in s.get("topics") or []:
        if extract_industry_from_reason(t.get("reason") or ""):
            found = True
            break
    if not found:
        still_empty += 1
print(f"\n完全无法 extract 的: {still_empty} / {len(stocks)}  ({still_empty/len(stocks)*100:.1f}%)")
