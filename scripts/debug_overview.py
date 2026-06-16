import json
with open('reference/market-limit/daily/2026-06-15.json', 'r', encoding='utf-8') as f:
    d = json.load(f)

ups = [s for s in d['stocks'] if s.get('isLimitUp')]
print(f"06-15: 涨停 {len(ups)} 只")
print("  前5:", [(s["code"], s["name"], s.get("limitUpStreak")) for s in ups[:5]])

# 大盘成交额走 eltdx, 不在 daily 文件里
# 检查 akshare latest snapshot
try:
    with open('reference/market-overview/akshare/latest.json', 'r', encoding='utf-8') as f:
        ak = json.load(f)
    print()
    print("akshare latest:")
    print(f"  tradingDate: {ak.get('tradingDate')}")
    print(f"  totalAmount: {ak.get('totalAmount')}")
    print(f"  mainNetInflow: {ak.get('mainNetInflow')}")
    print(f"  source: {ak.get('source')}")
except FileNotFoundError as e:
    print(f"akshare latest.json not found: {e}")

try:
    with open('reference/market-overview/market-overview/latest.json', 'r', encoding='utf-8') as f:
        el = json.load(f)
    print()
    print("eltdx latest:")
    print(f"  tradingDate: {el.get('tradingDate')}")
    print(f"  totalAmount: {el.get('totalAmount')}")
    print(f"  limitUpCount: {el.get('limitUpCount')}")
    print(f"  source: {el.get('source')}")
except FileNotFoundError as e:
    print(f"eltdx latest.json not found: {e}")
