import json

with open('reference/market-limit/daily/2026-06-15.json', 'r', encoding='utf-8') as f:
    daily = json.load(f)

print("=== 3 板股票 ===")
for s in daily['stocks']:
    if s.get('limitUpStreak') == 3:
        print(f"  {s['code']} {s['name']}: changePct={s.get('changePct')}")

print("\n=== 2 板股票 ===")
for s in daily['stocks']:
    if s.get('limitUpStreak') == 2:
        print(f"  {s['code']} {s['name']}: changePct={s.get('changePct')}")
