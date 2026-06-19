"""用 TDX sh000001 + sz399001 day 文件的 amount 字段回填 turnover_activity_daily.

数据流:
  sh000001.day + sz399001.day  (TDX 本地, 1990+ 完整)
  → 每日 amount 相加 (元 → 亿元) = 全市场成交额近似
  → ratio = total / 20日均
  → score = ratio 的 3y expanding-window 分位
  → 写入 turnover_activity_daily

为什么不直接走 market_overview_daily?
  → 那个表源是本地 akshare/eltdx archive, 没 archive 的日期就没数据 (2023-06 之前 0 行).
  → sh+sz 指数 TDX day 是离线本地文件, 1990+ 一直在, 覆盖 2018-2023 完美.

为什么不只用 daily_raw A 股 sum?
  → A 股 5000+ 只全量 sum daily_raw.amount 在 duckdb 也行, 但 sh+sz 指数 O(2 行) 更轻.
  → 用户建议的 sh+sz 指数相加, 覆盖 95% 流通市值, 误差 < 5%.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.adapters.market.duckdb_store import get_conn
from backend.services.stock.trading_calendar import is_trading_day

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("backfill_turnover_from_index")

# TDX sh + sz 指数 (覆盖 ~95% A 股市值)
SH_INDEX = "sh000001"   # 上证综指 (沪市全部)
SZ_INDEX = "sz399001"   # 深证成指 (深市主板 + 中小板)
TDX_DIR = Path(r"F:\dev-repo\mp4-to-word-new\reference\tdx\day\hsjday")
WINDOW = 20             # 20 日均


def _load_index_amounts(code: str) -> dict[date, float]:
    """读 TDX day 文件, 返回 {trade_date: amount_yi} (单位: 亿元)."""
    from scripts.tdx_parser import parse_day_file
    exchange = code[:2]
    fp = TDX_DIR / exchange / "lday" / f"{code}.day"
    if not fp.exists():
        raise FileNotFoundError(f"TDX day file not found: {fp}")
    r = parse_day_file(fp)
    # amount 单位: 元 → 转 亿元
    return {
        d: float(a) / 1e8
        for d, a in zip(r.df["trade_date"], r.df["amount"])
    }


def _backfill_one_day(td: date, sh_amt: dict, sz_amt: dict, con) -> bool:
    """算 td 的 total/avg/ratio, 写一行 turnover_activity_daily."""
    if not is_trading_day(td):
        return False
    if td not in sh_amt or td not in sz_amt:
        return False
    total = sh_amt[td] + sz_amt[td]
    # 过去 WINDOW (=20) 个交易日 (不含 td 自身)
    # 日历天 21 天 ≈ 15 个交易日, 不够 20; 实际 ~28 日历天才能凑 20 交易日, 取 60 天保险
    samples = []
    cur = td
    for _ in range(60):
        cur = cur - timedelta(days=1)
        if cur in sh_amt and cur in sz_amt:
            samples.append(sh_amt[cur] + sz_amt[cur])
            if len(samples) >= WINDOW:
                break
    if len(samples) < WINDOW:
        return False
    avg = sum(samples[:WINDOW]) / WINDOW
    ratio = total / avg if avg > 0 else None

    # score = ratio 的 3y expanding-window 分位
    score = None
    if ratio is not None:
        lb_start = td - timedelta(days=1060)
        r = con.execute("""
            SELECT 100.0 * COUNT(*) FILTER (WHERE ratio < ?)
                          / NULLIF(COUNT(*) FILTER (WHERE ratio IS NOT NULL), 0)
              FROM turnover_activity_daily
             WHERE trade_date >= ? AND trade_date < ?
        """, [ratio, lb_start, td]).fetchone()
        if r and r[0] is not None:
            score = round(float(r[0]), 2)

    con.execute("""
        INSERT OR REPLACE INTO turnover_activity_daily
            (trade_date, total_amount, avg_20d_amount, ratio, score,
             elapsed_ms, source, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, current_timestamp)
    """, [td, round(total, 2), round(avg, 2), round(ratio, 4) if ratio else None,
          score, 0, "tdx_sh_sz_index"])
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="用 TDX sh+sz 指数 amount 回填 turnover_activity_daily")
    ap.add_argument("--start", type=str, default="2018-01-01", help="起始日 (默认 2018-01-01)")
    ap.add_argument("--end", type=str, default="2026-06-18", help="结束日")
    args = ap.parse_args()

    log.info("读 TDX day: %s + %s ...", SH_INDEX, SZ_INDEX)
    sh_amt = _load_index_amounts(SH_INDEX)
    sz_amt = _load_index_amounts(SZ_INDEX)
    log.info("  sh: %d 天 (%s..%s)", len(sh_amt), min(sh_amt), max(sh_amt))
    log.info("  sz: %d 天 (%s..%s)", len(sz_amt), min(sz_amt), max(sz_amt))

    # 先 DELETE 现有 turnover 数据, 避免 source 混淆
    con = get_conn()
    n_before = con.execute("SELECT COUNT(*) FROM turnover_activity_daily").fetchone()[0]
    if n_before:
        con.execute("DELETE FROM turnover_activity_daily")
        log.info("清空旧 %d 行 (源切换到 tdx_sh_sz_index)", n_before)

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if end < start:
        log.error("end < start")
        return 1

    t0 = time.time()
    ok = 0
    cur = start
    while cur <= end:
        if is_trading_day(cur):
            if _backfill_one_day(cur, sh_amt, sz_amt, con):
                ok += 1
        cur = cur + timedelta(days=1)

    log.info("done: ok=%d in %.1fs", ok, time.time() - t0)
    # 复核
    r = con.execute("SELECT MIN(trade_date), MAX(trade_date), COUNT(*), AVG(ratio) FROM turnover_activity_daily").fetchone()
    log.info("coverage: %s ~ %s  count=%d  avg_ratio=%.3f", r[0], r[1], r[2], r[3])
    return 0


if __name__ == "__main__":
    sys.exit(main())
