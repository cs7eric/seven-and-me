import json
from collections import Counter

with open('reference/market-limit/daily/2026-06-15.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print(f"2026-06-15: total={len(data['stocks'])}")
streak_counter = Counter()
for s in data['stocks']:
    streak_counter[s.get('limitUpStreak', 0)] += 1

print('Streak distribution:')
for k in sorted(streak_counter.keys(), reverse=True):
    print(f'  {k}板: {streak_counter[k]}')

print()
print('Top 10 高板股票:')
top = sorted([s for s in data['stocks'] if s.get('limitUpStreak', 0) > 0], key=lambda x: -x['limitUpStreak'])[:10]
for s in top:
    print(f'  {s["code"]} {s["name"]}: streak={s["limitUpStreak"]}, isLimitUp={s["isLimitUp"]}, changePct={s.get("changePct")}')
