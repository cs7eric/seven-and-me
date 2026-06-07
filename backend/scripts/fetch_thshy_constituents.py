"""抓取同花顺行业成分股（支持分页）并打印 JSON。

示例:
  python backend/scripts/fetch_thshy_constituents.py 881121
  python backend/scripts/fetch_thshy_constituents.py 半导体 --refresh
"""
from __future__ import annotations

import argparse
import json

from backend.services.stock.f10.ths_industry_service import get_constituents_payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol", help="行业 code(881xxx) 或 行业名称")
    parser.add_argument("--refresh", action="store_true", help="忽略缓存，重新抓取")
    args = parser.parse_args()

    payload = get_constituents_payload(args.symbol, refresh=args.refresh)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
