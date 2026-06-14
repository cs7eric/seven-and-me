"""单独验证 universe meta 归一 (bj920634 ↔ 920634) + ST / 新股 识别."""
import sys, json
sys.path.insert(0, '.')
import backend.services.stock.limit_emotion_service as svc

# 清缓存
svc._universe_cache = None
svc._universe_loaded_at = 0

meta = svc._load_universe_meta(refresh=True)
print('universe meta entries:', len(meta))

# 验证 1: 6 位 code 和 full_code 都查得到同一份 entry
print()
print('=== 验证 1: 双 key 归一 ===')
test_pairs = [
    ('sh600519', '600519'),     # 主板
    ('sz000001', '000001'),     # 主板
    ('sz300750', '300750'),     # 创业板
    ('sh688981', '688981'),     # 科创板
    ('bj920634', '920634'),     # 北交所
    ('bj920006', '920006'),     # 北交所
]
for full, bare in test_pairs:
    e1 = meta.get(full)
    e2 = meta.get(bare)
    same = e1 is e2 and e1 is not None
    print(f'  {full:10s} <-> {bare:8s}  name="{e1.get("name") if e1 else "N/A":14s}"  is_st={e1.get("is_st") if e1 else "?"}  same={same}')

# 验证 2: ST 识别
print()
print('=== 验证 2: ST 识别 (从 ST板块 topic) ===')
st_codes = ['002610', '600519', '000038']  # 随便挑的, 看哪些被识别为 ST
for code in st_codes:
    e = meta.get(code) or meta.get('sh' + code) or meta.get('sz' + code) or meta.get('bj' + code)
    if e:
        is_st = e.get('is_st')
        name = e.get('name', '')
        # 找有 ST 板块 topic 的前 5 个
        if is_st:
            print(f'  ST: {code:8s} name="{name}"')

# 遍历前 20 个 ST stock
st_count = 0
for key, e in list(meta.items())[:2000]:
    if e.get('is_st') and st_count < 10:
        print(f'  ST: {key:12s} name="{e.get("name")}"')
        st_count += 1

# 验证 3: 新股识别
print()
print('=== 验证 3: 新股识别 (从 次新股 topic) ===')
new_count = 0
for key, e in list(meta.items()):
    if e.get('is_new') and new_count < 10:
        print(f'  NEW: {key:12s} name="{e.get("name")}"')
        new_count += 1

# 验证 4: name 填充率
print()
print('=== 验证 4: name 填充率 ===')
total = len(meta)
named = sum(1 for e in meta.values() if e.get('name'))
print(f'  total: {total}, with name: {named} ({100*named/total:.1f}%)')
