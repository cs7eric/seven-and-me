import sys, json, pathlib
sys.path.insert(0, '.')
from flask import Flask
from backend.api.stock_chart import stock_chart_bp
app = Flask('loop2')
app.register_blueprint(stock_chart_bp)

def _call(name, url, method='GET', **kw):
    with app.test_request_context(url, method=method, **kw):
        v = app.view_functions[name]()
        if isinstance(v, tuple):
            v = v[0]
        return v.get_json()

print('=== TEST: daily-snapshot on Sunday (should refuse) ===')
r = _call('stock_chart.market_pulse_limit_emotion_daily_snapshot',
          '/api/stock-chart/market-pulse/limit-emotion/daily-snapshot', method='POST')
print('  ok:', r.get('ok'))
print('  error:', r.get('error'))

print()
print('=== TEST: realtime limit-emotion (rebuilt universe meta) ===')
import backend.services.stock.limit_emotion_service as svc
svc._universe_cache = None
svc._universe_loaded_at = 0
r = _call('stock_chart.market_pulse_limit_emotion_refresh',
          '/api/stock-chart/market-pulse/limit-emotion/refresh', method='POST')
print('  tradeDate:', r.get('tradeDate'), '| marketStatus:', r.get('marketStatus'), '| dataStatus:', r.get('dataStatus'))
print('  limitUp.count:', r.get('limitUp', {}).get('count'))
print('  limitUp.stocks[0..5]:')
for s in (r.get('limitUp', {}).get('stocks') or [])[:5]:
    code = s.get('code', '')
    name = (s.get('name') or '')[:18]
    chg = s.get('changePct')
    up = s.get('limitUpPrice')
    print('   ', code.ljust(10), 'name=' + name.ljust(18), 'chg=' + str(chg), 'up=' + str(up))

buckets = {'10%': 0, '20%': 0, '30%': 0, '5%ST': 0}
for s in r.get('limitUp', {}).get('stocks') or []:
    cp = s.get('changePct')
    if cp is None: continue
    if abs(cp) >= 29: buckets['30%'] += 1
    elif abs(cp) >= 19: buckets['20%'] += 1
    elif abs(cp) >= 4.5 and abs(cp) < 5.5: buckets['5%ST'] += 1
    elif abs(cp) >= 9.5: buckets['10%'] += 1
print('  threshold buckets:', buckets)

stocks = r.get('limitUp', {}).get('stocks') or []
names_filled = sum(1 for s in stocks if s.get('name') and not s.get('name', '').isdigit())
print('  name fill rate:', names_filled, '/', len(stocks))

st = r.get('streak', {})
print('  streak.maxHeight:', st.get('maxHeight'))
print('  distribution[0:3]:', st.get('distribution', [])[:3])
print('  promotion:', st.get('promotion'))
print('  broken.count:', st.get('broken', {}).get('count'))
print('  sentiment:', st.get('sentiment'))
print('  _meta.source:', r.get('_meta', {}).get('source'))
print('  _meta.stockCount:', r.get('_meta', {}).get('stockCount'))
