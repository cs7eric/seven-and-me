import sys
sys.path.insert(0, '.')
from backend.services.stock.limit_emotion_service import build_limit_emotion

result = build_limit_emotion(force=True)
lu = result["limitUp"]
ld = result["limitDown"]
bb = result["breakBoard"]
st = result["streak"]
meta = result["_meta"]

print(f"limitUp count: {lu['count']}")
print(f"limitDown count: {ld['count']}")
print(f"breakBoard touched={bb['touchedCount']} broken={bb['brokenCount']} rate={bb['rate']}")
print(f"streak maxHeight: {st['maxHeight']}")
print(f"total stocks analyzed: {meta['stockCount']}")
print(f"source: {meta['source']}")
print()

by_thresh = {'main': 0, 'chinext_star': 0, 'bj': 0}
for s in lu['stocks']:
    code = s.get('code', '')
    if code.startswith(('30', '301', '688', '689')):
        by_thresh['chinext_star'] += 1
    elif code.startswith(('8', '4', '92')):
        by_thresh['bj'] += 1
    else:
        by_thresh['main'] += 1

print(f"limitUp by board: main={by_thresh['main']} chinext_star={by_thresh['chinext_star']} bj={by_thresh['bj']}")
print()

suspicious = [(s['code'], s['name'], s['changePct'], s.get('limitUpPrice'))
              for s in lu['stocks']
              if (s.get('changePct') or 0) > 25]
print(f"Stocks with changePct > 25% in limitUp list ({len(suspicious)}):")
for code, name, cp, up in suspicious:
    print(f"  {code} {name} chg={cp}% up={up}")