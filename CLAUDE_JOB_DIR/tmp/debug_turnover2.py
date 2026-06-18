"""debug turnover score."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.repositories.market.turnover_activity_repo import (
    calc_turnover_activity_cached,
)
import json as _json

# Try several recent dates
for td in ["2026-06-18", "2026-06-17", "2026-06-16"]:
    print(f"\n=== calc_turnover_activity_cached({td}) ===")
    p = calc_turnover_activity_cached(td)
    if p:
        print(_json.dumps(p, indent=2, ensure_ascii=False, default=str))
    else:
        print("  None")