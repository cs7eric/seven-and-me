import sys
sys.path.insert(0, '.')
from backend.services.stock.market_overview_akshare_service import _fetch_from_akshare, is_trade_time
from backend.services.stock.trading_calendar import is_trade_time as ical, is_trading_day
from datetime import datetime
import logging
logging.basicConfig(level=logging.WARNING)

now = datetime.now()
print(f"now: {now}, is_trade_time: {is_trade_time(now)}, is_trading_day: {is_trading_day(now.date())}")

# 尝试拉数据
result = _fetch_from_akshare()
if result is None:
    print("akshare fetch FAILED")
else:
    print("akshare fetch OK:")
    for k, v in result.items():
        if k != 'stocks':
            print(f"  {k}: {v}")
