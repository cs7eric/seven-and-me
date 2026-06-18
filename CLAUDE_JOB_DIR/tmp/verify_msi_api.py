"""调 repo 函数验证 (不依赖 Flask 路由)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.repositories.market.market_sentiment_index_repo import (
    calc_market_sentiment_index_cached,
    get_market_sentiment_index,
    get_market_sentiment_index_history,
)
import json as _json

# Snapshot 2026-06-18 (没落盘的一天, force 现算)
print("=== calc_market_sentiment_index_cached(2026-06-18) ===")
p = calc_market_sentiment_index_cached("2026-06-18", force=True)
if p:
    print(_json.dumps(p, indent=2, ensure_ascii=False, default=str))
else:
    print("  None")

# History
print("\n=== get_market_sentiment_index_history(2026-06-14, 2026-06-18) ===")
items = get_market_sentiment_index_history("2026-06-14", "2026-06-18")
for it in items:
    print(f"  {it['tradeDate']}  composite={it['compositeScore']:6.2f}  level={it['level']:8s}  cnt={it['componentCount']}/9")
