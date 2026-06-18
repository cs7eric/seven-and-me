"""回滚 6/17 损坏数据.

6/17 daily_raw 来自 TDX hsjday .day 文件, 数据本身损坏 (600519 6/16=1255, 6/17=124, 90% 跌幅不可能).
我的 fix_missing_qfq.py 把这个损坏的 raw 复制到 qfq/hfq, 进一步污染了 ma_count.

eltdx 实际上有正确的 6/17 数据 (600519 close=1240), 但完整 eltdx 重拉 12022 股票需要 30+ 分钟.

回滚:
  1. daily_qfq 删 6/17
  2. daily_hfq 删 6/17
  3. ma_count_daily 删 6/17
  4. daily_raw 6/17 保留 (用户可能想用, 标记为"待 eltdx 重拉")

  下一次 17:00 daily_eod_incremental scheduler 跑时, 调 eltdx 拉 6/17 (正确数据),
  6/17 就会自然有正确值.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.adapters.market.duckdb_store import get_conn


def main():
    con = get_conn()

    print("=" * 70)
    print("  回滚 6/17 损坏数据 (我之前 qfq=raw 兜底引入的污染)")
    print("=" * 70)

    for table in ("daily_qfq", "daily_hfq"):
        before = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        con.execute(f"DELETE FROM {table} WHERE trade_date = '2026-06-17'")
        after = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {before:,} -> {after:,} (-{before-after:,})")

    before = con.execute("SELECT COUNT(*) FROM ma_count_daily WHERE trade_date = '2026-06-17'").fetchone()[0]
    con.execute("DELETE FROM ma_count_daily WHERE trade_date = '2026-06-17'")
    after = con.execute("SELECT COUNT(*) FROM ma_count_daily WHERE trade_date = '2026-06-17'").fetchone()[0]
    print(f"  ma_count_daily 6/17: {before} -> {after}")

    print()
    print("=" * 70)
    print("  验证 6/17 已无数据:")
    print("=" * 70)
    for table in ("daily_qfq", "daily_hfq"):
        n = con.execute(f"SELECT COUNT(*) FROM {table} WHERE trade_date = '2026-06-17'").fetchone()[0]
        print(f"  {table} 6/17: {n} 行")

    print()
    print("=" * 70)
    print("  daily_raw 6/17 保留 (TDX 损坏, 但留给后续 eltdx 重拉作参照):")
    print("=" * 70)
    n = con.execute("SELECT COUNT(*) FROM daily_raw WHERE trade_date = '2026-06-17'").fetchone()[0]
    print(f"  daily_raw 6/17: {n:,} 行 (待 eltdx 正确数据覆盖)")

    print()
    print("=" * 70)
    print("  6/15, 6/16 验证没受影响 (应该是上次回填的正常值):")
    print("=" * 70)
    for td in ("2026-06-15", "2026-06-16", "2026-06-17"):
        for table in ("daily_qfq", "daily_hfq"):
            n = con.execute(f"SELECT COUNT(*) FROM {table} WHERE trade_date = ?", [td]).fetchone()[0]
            print(f"  {table} {td}: {n:,} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
