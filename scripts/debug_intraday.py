import sys
sys.path.insert(0, '.')
from backend.services.stock.kline_service import build_intraday_snapshot
from backend.api.stock_chart import sample_stock_klines

# 模拟前端传 trade_date=2026-06-16
try:
    snap, source = build_intraday_snapshot(
        'index', '000001', 'none', sample_stock_klines,
        trade_date='2026-06-16', periods=['1m'],
    )
    print(f'source: {source}')
    print(f'trade_date: {snap.get("trade_date")}')
    timeshare = snap.get('timeshare') or []
    print(f'timeshare bars: {len(timeshare)}')
    if timeshare:
        print(f'first: {timeshare[0]}')
        print(f'last: {timeshare[-1]}')
except Exception as exc:
    print(f'ERROR: {exc}')
