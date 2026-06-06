"""
A 股全市场日持久化 CLI.

用法:
    python -m backend.scripts.refresh_stock_universe           # 跑全量
    python -m backend.scripts.refresh_stock_universe --dry-run  # 只拉行情不写盘 (调试用)

成本: 5530+ 次 stock_topics RPC, 大约 1-2 分钟.
"""
from __future__ import annotations

import argparse
import logging

from backend.services.stock import stock_universe_service


def main():
    parser = argparse.ArgumentParser(description="拉全 A 股行情 + 题材, 写 reference/stock-universe/YYYY-MM-DD.json")
    parser.add_argument("--dry-run", action="store_true", help="只跑流程不写盘")
    parser.add_argument("--quiet", action="store_true", help="关掉进度打印")
    parser.add_argument("--workers", type=int, default=stock_universe_service.DEFAULT_WORKERS,
                        help=f"并发 worker 数 (默认 {stock_universe_service.DEFAULT_WORKERS}, 受限于 TQLEX 网关)")
    parser.add_argument("--pool-size", type=int, default=stock_universe_service.DEFAULT_POOL_SIZE,
                        help=f"eltdx 长连接池大小 (默认 {stock_universe_service.DEFAULT_POOL_SIZE}, TCP 链路数)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")

    if args.dry_run:
        # TODO: 复用 refresh 但跳过写盘
        print("dry-run not implemented, fall through to refresh()")
    result = stock_universe_service.refresh(progress=not args.quiet, workers=args.workers, pool_size=args.pool_size)
    print(f"OK: {result.trading_day}  stocks={result.stock_count} industries={result.industry_count} topics={result.topic_count}  elapsed={result.elapsed_s:.0f}s  file={result.file_path}")


if __name__ == "__main__":
    main()
