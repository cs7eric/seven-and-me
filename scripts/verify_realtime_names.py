"""直接验证 realtime quote 拿到后, universe meta 合并是否填上 name/is_st."""
import sys
sys.path.insert(0, '.')
import backend.services.stock.limit_emotion_service as svc

# 强制 reload
svc._universe_cache = None
svc._universe_loaded_at = 0

quotes, source, err = svc._fetch_realtime_quotes()
print('realtime quotes:', len(quotes), 'source:', source, 'err:', err)
print()

# 抽 10 只 涨停股
config = svc._load_config()
filtered = svc._apply_filters(quotes, config)
print('after filter:', len(filtered))

# 统计 name / is_st / is_new 填充率
total = len(filtered)
named = sum(1 for q in filtered if q.get('name') and not q.get('name', '').isdigit())
st = sum(1 for q in filtered if q.get('is_st'))
new = sum(1 for q in filtered if q.get('is_new'))
print(f'name fill rate: {named}/{total} ({100*named/total:.1f}%)')
print(f'is_st count: {st}')
print(f'is_new count: {new}')

# 抽几只看
print()
print('=== sample quotes (前 5 + 4 创 + 4 科 + 4 北) ===')
samples = []
seen_codes = set()
for q in filtered:
    code = q.get('code', '')
    if code[:2] in ('sh', 'sz') and code[2] in ('0', '6') and code not in seen_codes:
        samples.append(q); seen_codes.add(code)
    if code.startswith('sz30') and code not in seen_codes:
        samples.append(q); seen_codes.add(code)
    if code.startswith('sh688') and code not in seen_codes:
        samples.append(q); seen_codes.add(code)
    if code.startswith('bj') and code not in seen_codes:
        samples.append(q); seen_codes.add(code)
    if len(samples) >= 15:
        break
for q in samples:
    code = q.get('code', '')
    name = q.get('name', '')
    ex = q.get('exchange', '')
    is_st = q.get('is_st', False)
    is_new = q.get('is_new', False)
    print(f'  {code:10s} ex={ex:2s} name="{name:14s}" is_st={is_st} is_new={is_new}')

# 模拟涨停判定: 验证 4 档阈值
print()
print('=== threshold split on 涨停 ===')
limit_up, limit_down, bb = svc.calculate_limit_stats(filtered, config)['limitUp'], \
    svc.calculate_limit_stats(filtered, config)['limitDown'], \
    svc.calculate_limit_stats(filtered, config)['breakBoard']
print(f'limit up: {len(limit_up["stocks"])}')
print(f'limit down: {len(limit_down["stocks"])}')
print(f'breakBoard: touched={bb["touchedCount"]} broken={bb["brokenCount"]} rate={bb["rate"]}')

# 按 changePct 桶
buckets = {'10%': 0, '20%': 0, '30%': 0, '5%ST': 0}
for s in limit_up['stocks']:
    cp = s.get('changePct')
    if cp is None: continue
    if abs(cp) >= 29: buckets['30%'] += 1
    elif abs(cp) >= 19: buckets['20%'] += 1
    elif abs(cp) >= 4.5 and abs(cp) < 5.5: buckets['5%ST'] += 1
    elif abs(cp) >= 9.5: buckets['10%'] += 1
print(f'threshold buckets (limit up): {buckets}')

# 看几只涨停股的 name 是不是真的
print()
print('=== limit-up samples ===')
for s in limit_up['stocks'][:5]:
    print(f'  {s.get("code"):10s} name="{s.get("name"):14s}" chg={s.get("changePct")} up={s.get("limitUpPrice")}')
