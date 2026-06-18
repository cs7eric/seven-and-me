"""Backfill total market turnover history from Eastmoney API.

用法:
    # 在本地终端 (非此环境代理下) 执行:
    cd F:\dev-repo\mp4-to-word-new
    python scripts/backfill_turnover_from_em.py

数据流:
    1. 拉 Eastmoney 历史指数行情 (sh000001 上证综指, 含成交额)
    2. 计算全市场成交额 = 上证成交额 + 深证成交额
       (来自 sh000001+sz399001 的 index_daily_kline 接口)
    3. 写 market_overview_daily.total_amount
    4. 重新算 turnover_activity_daily

依赖:
    pip install requests
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("backfill_turnover")

# =========================================================================
# Eastmoney 指数日 K 线 API (历史)
# =========================================================================
# 参数:
#   secid: 1.000001 = 上证综指, 0.399001 = 深证成指
#   klt: 101 = 日k, 102 = 周k
#   lmt: 返回条数 (0=全部)
#   fqt: 1=前复权
#   fields1: f1,f2,f3,f4,f5,f6
#   fields2: f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61
#     f51=日期, f52=开盘, f53=收盘, f54=最高, f55=最低
#     f56=成交量, f57=成交额, f58=振幅, f59=涨跌幅, f60=涨跌额, f61=换手率

EM_INDEX_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
}

INDEX_CODES = [
    ("sh000001", "1.000001", "上证综指"),
    ("sz399001", "0.399001", "深证成指"),
]


def fetch_index_kline(secid: str, days: int = 3000) -> list[dict] | None:
    """拉一只指数的日 K 线 (含成交额)."""
    params = {
        "secid": secid,
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "1",
        "lmt": str(days),
    }
    try:
        import requests
        resp = requests.get(EM_INDEX_KLINE_URL, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        klines = (data or {}).get("data", {}).get("klines", [])
        if not klines:
            log.warning("  API returned empty klines for secid=%s", secid)
            return None
        result = []
        for line in klines:
            parts = str(line).split(",")
            if len(parts) < 11:
                continue
            try:
                result.append({
                    "date": parts[0].strip(),
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": float(parts[5]),    # 成交量 (手)
                    "amount": float(parts[6]),     # 成交额 (元)
                    "amplitude": float(parts[7]),
                    "change_pct": float(parts[8]),
                    "change_amount": float(parts[9]),
                    "turnover_rate": float(parts[10]),
                })
            except (ValueError, IndexError):
                continue
        log.info("  [%s] fetched %d klines, last=%s close=%.2f amount=%.0f亿",
                 secid, len(result), result[-1]["date"] if result else "-",
                 result[-1]["close"] if result else 0,
                 (result[-1]["amount"] / 1e8) if result else 0)
        return result
    except Exception as exc:
        log.warning("  fetch failed for secid=%s: %s", secid, exc)
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill total market turnover from Eastmoney")
    ap.add_argument("--days", type=int, default=3000, help="拉取天数 (默认 3000 ≈ 12 年)")
    ap.add_argument("--start", type=str, default=None, help="起始日期 YYYY-MM-DD (覆盖 --days)")
    ap.add_argument("--end", type=str, default=None, help="结束日期 YYYY-MM-DD (默认今天)")
    ap.add_argument("--force", action="store_true", help="覆盖已有 market_overview_daily 记录")
    args = ap.parse_args()

    # Step 1: Fetch index klines
    log.info("=== Step 1: Fetch index klines from Eastmoney ===")
    all_data: dict[str, dict] = {}
    for full_code, secid, name in INDEX_CODES:
        rows = fetch_index_kline(secid, days=args.days)
        if not rows:
            log.error("  Failed to fetch %s (%s), abort", name, secid)
            return 1
        for r in rows:
            dt = r["date"]
            if dt not in all_data:
                all_data[dt] = {"date": dt, "sh_amount_yi": 0.0, "sz_amount_yi": 0.0}
            yi = r["amount"] / 1e8
            if "sh" in full_code:
                all_data[dt]["sh_amount_yi"] = yi
            else:
                all_data[dt]["sz_amount_yi"] = yi

    # Combine SH + SZ = total market turnover
    merged = []
    for dt in sorted(all_data.keys()):
        d = all_data[dt]
        total = d["sh_amount_yi"] + d["sz_amount_yi"]
        merged.append({
            "tradeDate": dt,
            "totalAmount": round(total, 2),
            "shAmount": d["sh_amount_yi"],
            "szAmount": d["sz_amount_yi"],
        })
    log.info("  Merged %d trading days (SH+SZ)", len(merged))

    if args.start:
        merged = [m for m in merged if m["tradeDate"] >= args.start]

    # Filter by date range
    end_date = args.end or date.today().isoformat()
    merged_final = [m for m in merged if m["tradeDate"] <= end_date]
    if merged_final:
        log.info("  Range: %s ~ %s, %d days, sample:",
                 merged_final[0]["tradeDate"], merged_final[-1]["tradeDate"], len(merged_final))
        for m in merged_final[-3:]:
            log.info("    %s: total=%.0f亿 (SH=%.0f + SZ=%.0f)",
                     m["tradeDate"], m["totalAmount"], m["shAmount"], m["szAmount"])
    else:
        log.warning("  No data after filtering")

    # Step 2: Upsert into market_overview_daily (字段级: 只写 total_amount, 不碰已有字段)
    log.info("\n=== Step 2: Upsert into market_overview_daily ===")
    from backend.adapters.market.duckdb_store import get_conn
    from backend.repositories.market.market_overview_repo import upsert_overview_akshare

    con = get_conn()

    before = con.execute("SELECT COUNT(*) FROM market_overview_daily").fetchone()[0]
    written = 0
    skipped = 0
    for m in merged_final:
        td = date.fromisoformat(m["tradeDate"])
        if not args.force:
            existing = con.execute(
                "SELECT total_amount FROM market_overview_daily WHERE trade_date = ?",
                [td],
            ).fetchone()
            if existing and existing[0] is not None:
                skipped += 1
                continue
        # 先用 INSERT OR IGNORE 建行 (如果不存在)
        con.execute(
            "INSERT OR IGNORE INTO market_overview_daily (trade_date, source) VALUES (?, 'eastmoney_hist')",
            [td],
        )
        # 再用 UPDATE 只写 total_amount (不覆盖已有的资金流/涨跌家数字段)
        con.execute(
            "UPDATE market_overview_daily SET total_amount = ? WHERE trade_date = ?",
            [float(m["totalAmount"]), td],
        )
        written += 1

    after = con.execute("SELECT COUNT(*) FROM market_overview_daily").fetchone()[0]
    log.info("  Written: %d, Skipped (exists): %d, Before: %d, After: %d",
             written, skipped, before, after)

    # Step 3: Recompute turnover_activity_daily
    log.info("\n=== Step 3: Recompute turnover_activity_daily ===")
    from backend.repositories.market.turnover_activity_repo import (
        calc_turnover_activity_cached,
    )

    # Get all trading dates with total_amount in market_overview_daily
    rows = con.execute("""
        SELECT trade_date FROM market_overview_daily
        WHERE total_amount IS NOT NULL AND total_amount > 0
        ORDER BY trade_date
    """).fetchall()
    trade_dates = [r[0] for r in rows if r[0] is not None]
    log.info("  Found %d dates with total_amount", len(trade_dates))

    # Check existing turnover_activity_daily coverage
    r = con.execute("SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM turnover_activity_daily").fetchone()
    log.info("  turnover_activity_daily before: %s ~ %s (%d rows)", r[0], r[1], r[2])

    t0 = time.time()
    ok = fail = 0
    for i, td in enumerate(trade_dates):
        try:
            payload = calc_turnover_activity_cached(td, force=args.force)
            if payload and payload.get("ratio") is not None:
                ok += 1
            else:
                fail += 1
        except Exception as exc:
            log.debug("  %s failed: %s", td, exc)
            fail += 1
        if (i + 1) % 200 == 0:
            log.info("  [%d/%d] ok=%d fail=%d", i + 1, len(trade_dates), ok, fail)

    elapsed = time.time() - t0
    log.info("  turnover done: ok=%d fail=%d in %.1fs", ok, fail, elapsed)

    r = con.execute("SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM turnover_activity_daily").fetchone()
    log.info("  turnover_activity_daily after: %s ~ %s (%d rows)", r[0], r[1], r[2])

    log.info("\n=== Done ===")
    log.info("Total market turnover backfilled for %d days", written)
    log.info("Turnover activity recomputed for %d days", ok)

    # Print sample
    r = con.execute("""
        SELECT trade_date, total_amount FROM market_overview_daily
        WHERE total_amount IS NOT NULL AND source = 'eastmoney_hist'
        ORDER BY trade_date DESC LIMIT 5
    """).fetchall()
    log.info("Sample backfilled data:")
    for row in r:
        log.info("  %s: %.0f亿", row[0], float(row[1]))

    return 0


if __name__ == "__main__":
    sys.exit(main())
