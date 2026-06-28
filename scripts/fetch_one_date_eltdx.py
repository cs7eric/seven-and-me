"""Focused fetch: 调 eltdx 拉单个交易日 (默认 6/17) 的 qfq/hfq 数据, 写到 ClickHouse daily_qfq/daily_hfq.

比 fetch_eltdx_adjusted_kline.py 更快:
  - 只取最近 10 天 (~ 3 次 API 调用足够覆盖 6/17 + 历史)
  - 只对 stock_meta_repo universe (5530 只 A 股) 跑, 跳过 9452 daily_raw 里的 ETF/退市/指数
  - 32 workers 并发, 实际 5-10 分钟搞定

Usage:
  python scripts/fetch_one_date_eltdx.py [--date=2026-06-17] [--adjust=both]
"""
import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from eltdx import TdxClient

from backend.adapters.market.clickhouse_store import command, insert, query_one
from backend.repositories.market.stock_meta_repo import _codes_json


_workers = []


def _get_client(timeout: int = 8) -> TdxClient:
    """每个 worker 一个 TdxClient (TCP 长连接)."""
    from threading import current_thread
    if not hasattr(current_thread(), "client"):
        current_thread().client = TdxClient(timeout=timeout)
    return current_thread().client


def _to_full_code(code: str) -> str:
    return f"sh{code}" if code.startswith(("5", "6", "9")) else f"sz{code}"


def _fetch_one(code: str, anchor_date: str, max_retries: int = 3) -> tuple[list, str | None]:
    """拉 1 只股票在 anchor_date 及之前 10 天的 qfq 数据."""
    last_err: str | None = None
    for attempt in range(max_retries + 1):
        try:
            client = _get_client()
            full_code = _to_full_code(code)
            series = client.get_adjusted_kline(
                period='day', code=full_code, adjust='qfq',
                anchor_date=anchor_date, start=0, count=10,
            )
            bars = series.bars if hasattr(series, "bars") else series.items
            if bars:
                rows = []
                for r in bars:
                    rows.append((
                        code, r.time.date(),
                        float(r.open), float(r.high), float(r.low), float(r.close),
                        int(r.volume_lots) if r.volume_lots is not None else 0,
                        float(r.amount) if r.amount is not None else 0.0,
                    ))
                return rows, None
            last_err = "empty result"
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
        if attempt < max_retries:
            time.sleep([1, 3, 9][min(attempt, 2)])
    return [], last_err


def _quote_ch_strings(values: list[str]) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


def _bulk_insert(target: str, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    codes = sorted(str(c) for c in df["code"].dropna().unique())
    min_date = df["trade_date"].min()
    max_date = df["trade_date"].max()
    if codes:
        command(
            f"ALTER TABLE {target} DELETE "
            f"WHERE code IN ({_quote_ch_strings(codes)}) "
            f"AND trade_date BETWEEN toDate('{min_date}') AND toDate('{max_date}')",
            settings={"mutations_sync": 1},
        )
    now = datetime.now()
    rows = [
        (
            str(r.code),
            r.trade_date,
            float(r.open),
            float(r.high),
            float(r.low),
            float(r.close),
            int(r.volume),
            float(r.amount),
            1.0,
            now,
        )
        for r in df.itertuples(index=False)
    ]
    insert(
        target,
        rows,
        ["code", "trade_date", "open", "high", "low", "close", "volume", "amount", "adj_factor", "ingested_at"],
    )
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--date",
        default=os.environ.get("MINIMAX_TARGET_TRADE_DATE", ""),
        help="目标日 (默认取环境变量 MINIMAX_TARGET_TRADE_DATE, 如 2026-06-19)",
    )
    ap.add_argument("--adjust", choices=["qfq", "hfq", "both"], default="both")
    ap.add_argument("--workers", type=int, default=32)
    args = ap.parse_args()

    run(date_str=args.date, adjust=args.adjust, workers=args.workers)


def run(date_str: str, adjust: str = "both", workers: int = 32) -> dict:
    """In-process 入口.

    Returns:
        {"qfq_rows": int, "hfq_rows": int, "elapsed": float}
    """
    # 1. universe: stock_meta_repo._codes.json 的 5530 只 A 股 (active)
    all_codes = list(_codes_json().keys())
    print(f"universe: {len(all_codes)} A-share codes (from _codes.json)")

    # 2. 对每个 (code, date) 调 eltdx, 写入 ClickHouse daily_qfq / daily_hfq
    completed = 0
    err_count = 0
    grand_qfq = 0
    grand_hfq = 0
    t0 = time.time()

    for adj in (["qfq"] if adjust == "qfq" else
                ["hfq"] if adjust == "hfq" else ["qfq", "hfq"]):
        print(f"--- {adj} ---")
        all_rows = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_fetch_one, code, date_str): code for code in all_codes}
            for fut in as_completed(futures):
                code = futures[fut]
                completed += 1
                try:
                    rows, err = fut.result()
                except Exception as exc:
                    err = f"{type(exc).__name__}: {exc}"
                    rows = []
                if err:
                    err_count += 1
                    if err_count <= 5:
                        print(f"  ! {code}: {err}", flush=True)
                else:
                    all_rows.extend(rows)

                if completed % 200 == 0 or completed == len(all_codes):
                    elapsed = time.time() - t0
                    rate = completed / elapsed if elapsed else 0
                    eta = (len(all_codes) - completed) / rate if rate else 0
                    print(
                        f"  [{completed:>5d}/{len(all_codes)}]  "
                        f"{rate:>4.1f} stk/s  rows={len(all_rows):>7,}  "
                        f"err={err_count:>3d}  ETA {eta:>4.0f}s",
                        flush=True,
                    )

        if all_rows:
            df = pd.DataFrame(all_rows, columns=[
                "code", "trade_date", "open", "high", "low", "close", "volume", "amount"
            ])
            n = _bulk_insert(f"daily_{adj}", df)
            if adj == "qfq":
                grand_qfq = n
            else:
                grand_hfq = n
            print(f"  daily_{adj}: +{n:,} rows")

    elapsed = time.time() - t0
    print()
    print(f"done in {elapsed:.1f}s ({elapsed/60:.1f} min)")
    print(f"  errors: {err_count}")

    # 3. 验证
    print()
    print(f"=== 验证 {date_str} ===")
    for table in ("daily_qfq", "daily_hfq"):
        n = query_one(f"SELECT COUNT(*), COUNT(DISTINCT code) FROM {table} WHERE trade_date = %s", (date_str,))
        print(f"  {table} {date_str}: {n[0]:,} rows, {n[1]:,} distinct codes")
    return {
        "qfq_rows": grand_qfq,
        "hfq_rows": grand_hfq,
        "elapsed": elapsed,
        "errors": err_count,
    }


if __name__ == "__main__":
    sys.exit(main())
