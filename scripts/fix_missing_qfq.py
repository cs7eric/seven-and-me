"""Fast fix: 把 daily_raw 里缺失 qfq 的 trade_date 复制到 daily_qfq / daily_hfq.

6/17 daily_qfq 漏了, 因为 daily_eod 的 step 2-5 (qfq ETL) 没跑.
跑完整 daily_eod 需要 30+ 分钟 (eltdx 重拉 12022 股票).

这个脚本只做 raw → qfq/hfq 的兜底:
  1. daily_qfq 缺的 trade_date (按 code), 用 daily_raw 复制, adj_factor=1.0
  2. daily_hfq 缺的 trade_date (按 code), 同样复制
  3. 不重新拉 eltdx (那种方式更准确但慢)

影响:
  - 大部分股票前/后复权 = raw (没有 corp events 在 6/17 发生)
  - 极少数近期有 corp events (分红送股) 的股票, 复权会略偏 → 但 6/17 当天的 MA 计数受影响很小
  - 跟 fallback_remaining_ashares.py 同口径 (Plan A: 拉不到 eltdx 的就用 raw 兜)

使用: python scripts/fix_missing_qfq.py [--dry-run]
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.adapters.market.duckdb_store import get_conn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只统计, 不写")
    args = ap.parse_args()

    con = get_conn()

    # 1. 找 daily_raw 有但 daily_qfq 没有的 (code, trade_date)
    print("=" * 70)
    print("  6/17 daily_raw 存在, daily_qfq 缺失的 (code, trade_date) 数量:")
    print("=" * 70)
    rows = con.execute("""
        SELECT trade_date, COUNT(*) AS n
          FROM (
            SELECT r.code, r.trade_date
              FROM daily_raw r
              ANTI JOIN daily_qfq q
                ON q.code = r.code AND q.trade_date = r.trade_date
          ) m
         GROUP BY trade_date
         ORDER BY trade_date DESC
         LIMIT 10
    """).fetchall()
    for td, n in rows:
        print(f"  {td}: {n:>8,} missing (code, trade_date) pairs")

    if args.dry_run:
        print("\n[dry-run] no writes")
        return 0

    # 2. daily_qfq 兜底: raw → qfq, adj_factor=1.0
    print()
    print("=" * 70)
    print("  Filling daily_qfq (raw → qfq, adj_factor=1.0, NOT EXISTS)...")
    print("=" * 70)
    t0 = time.time()
    con.execute("""
        INSERT INTO daily_qfq (code, trade_date, open, high, low, close,
                               volume, amount, adj_factor, ingested_at)
        SELECT r.code, r.trade_date, r.open, r.high, r.low, r.close,
               r.volume, r.amount, 1.0, current_timestamp
          FROM daily_raw r
         WHERE NOT EXISTS (
             SELECT 1 FROM daily_qfq q
              WHERE q.code = r.code AND q.trade_date = r.trade_date
         )
    """)
    elapsed = time.time() - t0
    n = con.execute("SELECT count(*) FROM daily_qfq").fetchone()[0]
    print(f"  done in {elapsed:.1f}s, daily_qfq total: {n:,}")

    # 3. daily_hfq 兜底 (用 INSERT OR IGNORE 避免 NOT EXISTS 在 dup key 时炸)
    print()
    print("=" * 70)
    print("  Filling daily_hfq (raw → hfq, adj_factor=1.0, NOT EXISTS)...")
    print("=" * 70)
    t0 = time.time()
    con.execute("""
        INSERT OR IGNORE INTO daily_hfq (code, trade_date, open, high, low, close,
                                          volume, amount, adj_factor, ingested_at)
        SELECT r.code, r.trade_date, r.open, r.high, r.low, r.close,
               r.volume, r.amount, 1.0, current_timestamp
          FROM daily_raw r
         WHERE NOT EXISTS (
             SELECT 1 FROM daily_hfq h
              WHERE h.code = r.code AND h.trade_date = r.trade_date
         )
    """)
    elapsed = time.time() - t0
    n = con.execute("SELECT count(*) FROM daily_hfq").fetchone()[0]
    print(f"  done in {elapsed:.1f}s, daily_hfq total: {n:,}")

    # 4. 验证 6/17
    print()
    print("=" * 70)
    print("  验证 6/17 daily_qfq 行数:")
    print("=" * 70)
    for td in ("2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18"):
        n = con.execute("SELECT COUNT(*), COUNT(DISTINCT code) FROM daily_qfq WHERE trade_date = ?", [td]).fetchone()
        print(f"  {td}: {n[0]:>8,} rows, {n[1]:>6,} distinct codes")

    return 0


if __name__ == "__main__":
    sys.exit(main())
