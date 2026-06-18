"""ths_industry_fund_flow_daily 端到端 smoke test."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 重要: 用 conn() contextmanager, 不用 get_conn() 直接 with
# (DuckDBPyConnection.__exit__ 会 close, 导致后续 _local.conn 失效)
from backend.adapters.market.duckdb_store import conn, init_schema
from backend.repositories.market.ths_industry_fund_flow_repo import (
    upsert_fund_flow, get_fund_flow_daily, get_fund_flow_daily_topn,
    get_fund_flow_history, get_fund_flow_for_names, coverage,
)

# 0. schema 初始化 (幂等, 加了新表后必须跑一次才会创建)
init_schema()
print("schema 初始化完成")

# 1. 准备
with conn() as c:
    c.execute(
        "DELETE FROM ths_industry_fund_flow_daily "
        "WHERE trade_date IN ('2026-06-15', '2026-06-16')"
    )
print("cleaned")

# 2. upsert 2 天 / 各 3 行业 (mock)
rows_0615 = [
    {"industry": "半导体", "industry_code": "881268", "rank": 1, "change_pct": 2.35, "inflow": 25.5, "outflow": 12.3, "net": 13.2, "company_count": 142, "leader_stock": "中芯国际", "leader_change": 5.1, "leader_price": 85.3},
    {"industry": "银行",   "industry_code": "881155", "rank": 2, "change_pct": -0.85, "inflow": 5.0, "outflow": 8.0, "net": -3.0, "company_count": 42, "leader_stock": "工商银行", "leader_change": -0.5, "leader_price": 6.5},
    {"industry": "新能源", "industry_code": "881120", "rank": 3, "change_pct": 1.20, "inflow": 10.0, "outflow": 6.0, "net": 4.0, "company_count": 95, "leader_stock": "宁德时代", "leader_change": 3.0, "leader_price": 220.0},
]
rows_0616 = [
    {"industry": "半导体", "industry_code": "881268", "rank": 1, "change_pct": 3.50, "inflow": 30.0, "outflow": 10.0, "net": 20.0, "company_count": 142, "leader_stock": "中芯国际", "leader_change": 6.0, "leader_price": 87.0},
    {"industry": "银行",   "industry_code": "881155", "rank": 2, "change_pct": 0.50, "inflow": 7.0, "outflow": 6.5, "net": 0.5, "company_count": 42, "leader_stock": "工商银行", "leader_change": 0.8, "leader_price": 6.6},
]
n1 = upsert_fund_flow(rows_0615, trade_date="2026-06-15")
n2 = upsert_fund_flow(rows_0616, trade_date="2026-06-16")
print(f"upserted: 0615={n1}, 0616={n2}")

# 3. 单日 (按 net DESC)
print("--- get_fund_flow_daily(2026-06-16) ---")
print(json.dumps(get_fund_flow_daily("2026-06-16"), indent=2, ensure_ascii=False))

# 4. 单日 TopN
print("--- get_fund_flow_daily_topn(2026-06-15, topN=2) ---")
print(json.dumps(get_fund_flow_daily_topn("2026-06-15", top_n=2), indent=2, ensure_ascii=False))

# 5. 历史序列
print("--- get_fund_flow_history(days=2, topN=2) ---")
print(json.dumps(get_fund_flow_history(days=2, top_n=2), indent=2, ensure_ascii=False))

# 6. 按行业名查
print("--- get_fund_flow_for_names(2026-06-16, ['半导体', '银行']) ---")
print(json.dumps(get_fund_flow_for_names("2026-06-16", ["半导体", "银行"]), indent=2, ensure_ascii=False))

# 7. 覆盖度
print("--- coverage ---")
print(json.dumps(coverage(), indent=2, ensure_ascii=False))
