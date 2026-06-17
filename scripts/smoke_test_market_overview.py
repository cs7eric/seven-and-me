"""market_overview_daily COALESCE 保护测试."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.adapters.market.duckdb_store import conn
from backend.repositories.market.market_overview_repo import upsert_overview_akshare, upsert_overview_eltdx, get_overview

# clean (用 conn() contextmanager, 不会触发 DuckDBPyConnection.__exit__ close)
with conn() as c:
    c.execute("DELETE FROM market_overview_daily WHERE trade_date = '2026-06-16'")
print('cleaned')

# 1) akshare 先写
upsert_overview_akshare({
    'tradingDate': '2026-06-16',
    'totalAmount': 12345.67,
    'risingCount': 3850, 'fallingCount': 1230, 'flatCount': 145,
    'limitUpCount': 88, 'limitDownCount': 2, 'stockCount': 5230,
    'mainNetInflow': -287.5, 'source': 'akshare',
})

# 2) eltdx 后写 (totalAmount / risingCount / fallingCount 已存在, 不应覆盖)
upsert_overview_eltdx({
    'tradingDate': '2026-06-16',
    'totalAmount': 12350.0,
    'risingCount': 3855, 'fallingCount': 1225,
    'source': 'eltdx',
})

# 3) 再 akshare (totalAmount 已存在, 不应被新值 99999 覆盖)
upsert_overview_akshare({
    'tradingDate': '2026-06-16',
    'totalAmount': 99999.99,
    'risingCount': 9999, 'fallingCount': 9999, 'flatCount': 9999,
    'source': 'akshare',
})

row = get_overview('2026-06-16')
print(json.dumps(row, indent=2, ensure_ascii=False))
