import sys
sys.path.insert(0, '.')
from backend.services.stock.limit_emotion_service import _read_json_safe
from pathlib import Path

daily_dir = Path('reference/market-limit/daily')
for f in sorted(daily_dir.glob('*.json')):
    data = _read_json_safe(f)
    if data:
        stocks = data.get('stocks', [])
        lu = sum(1 for s in stocks if s.get('isLimitUp'))
        ld = sum(1 for s in stocks if s.get('isLimitDown'))
        print(f'{f.name}: {len(stocks)} stocks, limitUp={lu}, limitDown={ld}, tradeDate={data.get("tradeDate")}')