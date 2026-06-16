import json

with open('reference/market-limit/daily/2026-06-15.json', 'r', encoding='utf-8') as f:
    daily = json.load(f)

# 找 000510
for s in daily['stocks']:
    if s.get('code') == '000510':
        print('000510 in 06-15 daily:')
        for k, v in s.items():
            print(f'  {k}: {v}')
        break

# 再找 601958, 000032
for code in ['601958', '000032', '001257']:
    for s in daily['stocks']:
        if s.get('code') == code:
            print(f'\n{code} in 06-15 daily:')
            print(f'  limitUpStreak: {s.get("limitUpStreak")}')
            print(f'  previousLimitUpStreak: {s.get("previousLimitUpStreak")}')
            print(f'  isLimitUp: {s.get("isLimitUp")}')
            print(f'  isPromoted: {s.get("isPromoted")}')
            print(f'  changePct: {s.get("changePct")}')
            break
