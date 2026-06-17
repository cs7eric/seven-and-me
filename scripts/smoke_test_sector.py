"""market_pulse_sector_daily smoke test."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.adapters.market.duckdb_store import conn
from backend.repositories.market.market_pulse_sector_repo import (
    upsert_sector_spot, get_sector_daily, get_sector_daily_topn,
    get_sector_history, get_sector_for_names, coverage,
)

with conn() as c:
    c.execute("DELETE FROM market_pulse_sector_daily WHERE trade_date IN ('2026-06-15', '2026-06-16')")
print('cleaned')

# 1) 写入 90 行业 (2 天)
rows_0615 = [
    {"name": "半导体", "index": "880491", "changePct": 2.35, "inflow": 12.5, "outflow": 8.2, "mainNet": 4.3, "stockCount": 142, "leadingStock": "中芯国际", "leadingChangePct": 5.1, "leadingPrice": 85.3},
    {"name": "银行",   "index": "880471", "changePct": -0.85, "inflow": 5.0,  "outflow": 8.0, "mainNet": -3.0, "stockCount": 42, "leadingStock": "工商银行", "leadingChangePct": -0.5, "leadingPrice": 6.5},
    {"name": "新能源", "index": "880446", "changePct": 1.20, "inflow": 10.0, "outflow": 6.0, "mainNet": 4.0, "stockCount": 95, "leadingStock": "宁德时代", "leadingChangePct": 3.0, "leadingPrice": 220.0},
]
rows_0616 = [
    {"name": "半导体", "index": "880491", "changePct": 3.50, "inflow": 15.0, "outflow": 7.0, "mainNet": 8.0, "stockCount": 142, "leadingStock": "中芯国际", "leadingChangePct": 6.0, "leadingPrice": 87.0},
    {"name": "银行",   "index": "880471", "changePct": 0.50,  "inflow": 7.0,  "outflow": 6.5, "mainNet": 0.5,  "stockCount": 42, "leadingStock": "工商银行", "leadingChangePct": 0.8, "leadingPrice": 6.6},
]
n1 = upsert_sector_spot(rows_0615, trade_date="2026-06-15")
n2 = upsert_sector_spot(rows_0616, trade_date="2026-06-16")
print(f"upserted: 0615={n1}, 0616={n2}")

print('--- get_sector_daily(2026-06-16) ---')
print(json.dumps(get_sector_daily("2026-06-16"), indent=2, ensure_ascii=False))

print('--- get_sector_daily_topn(2026-06-15, topN=2) ---')
print(json.dumps(get_sector_daily_topn("2026-06-15", top_n=2), indent=2, ensure_ascii=False))

print('--- get_sector_history(days=2) ---')
print(json.dumps(get_sector_history(days=2, top_n=2), indent=2, ensure_ascii=False))

print('--- get_sector_for_names(2026-06-16, ["半导体", "银行"]) ---')
print(json.dumps(get_sector_for_names("2026-06-16", ["半导体", "银行"]), indent=2, ensure_ascii=False))

print('--- coverage ---')
print(json.dumps(coverage(), indent=2, ensure_ascii=False))
