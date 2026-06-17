"""拉宽基指数 K 线 (沪深300 / 中证1000) → 落 duckdb index_daily_raw.

用法:
    python scripts/fetch_index_history.py [--days=30] [--codes=000300,000852]

数据源优先级: tencent (HTTP 500 bars/req, 已知工作) → eastmoney 兜底.
落盘:   reference/stock/duckdb/market_data.duckdb / index_daily_raw 表
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# 兼容 scripts/ 目录独立执行
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.adapters.market.eastmoney import fetch_stock_klines_from_eastmoney
from backend.adapters.market.tencent import fetch_stock_klines_from_tencent
from backend.repositories.market.index_repo import INDEX_TARGETS, upsert_index_daily

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("fetch_index_history")


def _fetch_one_index(code: str) -> tuple[list[dict], str] | None:
    """对单只指数依次尝试 tencent → eastmoney. 返回 (items, source) 或 None."""
    for fetcher, src in (
        (lambda: fetch_stock_klines_from_tencent("index", code, "1d", "qfq"),
         "tencent"),
        (lambda: fetch_stock_klines_from_eastmoney("index", code, "1d", "qfq"),
         "eastmoney"),
    ):
        try:
            cand = fetcher()
            if cand:
                return cand, src
        except Exception as exc:  # noqa: BLE001
            log.debug("  %s 失败: %s", src, exc)
            continue
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="拉宽基指数 K 线到 duckdb")
    parser.add_argument(
        "--days", type=int, default=30,
        help="拉最近 N 天的 K 线 (默认 30, 增量时 2 即可)",
    )
    parser.add_argument(
        "--codes", type=str, default="",
        help="逗号分隔的 6 位 code, 默认全 INDEX_TARGETS (000300,000852)",
    )
    args = parser.parse_args()

    if args.codes.strip():
        wanted_codes = {c.strip() for c in args.codes.split(",") if c.strip()}
        targets = [t for t in INDEX_TARGETS if t["code"] in wanted_codes]
    else:
        targets = list(INDEX_TARGETS)

    log.info("开始拉 %d 只宽基指数, days=%d ...", len(targets), args.days)
    t0 = time.time()
    total_rows = 0
    fail: list[str] = []
    for tgt in targets:
        result = _fetch_one_index(tgt["code"])
        if result is None:
            log.warning("  [%s %s] 所有数据源失败, 跳过", tgt["name"], tgt["code"])
            fail.append(tgt["code"])
            continue
        items, source = result
        # tencent / eastmoney 都返回 trade_date (YYYY-MM-DD), 标准化
        rows: list[dict] = []
        for it in items:
            td = it.get("trade_date") or it.get("date")
            if not td:
                continue
            rows.append({
                "trade_date": str(td)[:10],
                "open": it.get("open"),
                "high": it.get("high"),
                "low": it.get("low"),
                "close": it.get("close"),
                "volume": it.get("volume") or 0,
                "amount": it.get("amount") or 0,
            })
        rows = rows[-args.days:]
        try:
            n = upsert_index_daily(tgt["full"], rows, source=source)
            total_rows += n
            log.info(
                "  [%s %s] 写入 %d 条 (源=%s), 最后一日=%s close=%.2f",
                tgt["name"], tgt["code"], n, source,
                rows[-1]["trade_date"] if rows else "-",
                float(rows[-1]["close"]) if rows else 0,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("  [%s %s] 写入失败: %s", tgt["name"], tgt["code"], exc)
            fail.append(tgt["code"])

    elapsed = time.time() - t0
    log.info(
        "完成: %d 只指数, 共写入 %d 条, 耗时 %.1fs, 失败 %s",
        len(targets), total_rows, elapsed, fail or "无",
    )
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
