"""每日 EOD 增量入 duckdb 编排器 (供 17:00 scheduler 调用).

逻辑:
  1. 查 duckdb daily_raw 当前最大 trade_date
  2. 与今天对比, 缺 N 天 → 调 initial_backfill.py (INSERT OR IGNORE 幂等,
     重复跑不会写脏数据, 会自动补齐缺的日期)
  3. 跑完 → 调 backfill_limit_emotion_summary.py --days=N+2 回算
     缺日的 limit_emotion_summary_daily (涨跌停情绪综合分)

跟 daily_eod.py 区别:
  - daily_eod.py 跑全套 8 步 (qfq/hfq/validate/MA 计数等), 是手动一次性
  - 这个脚本只跑"补数据 + limit 缓存"两件事, 快 (< 4.5 min), 适合每天 17:00

安全:
  - 工作日 / 周末 / 节假日都能跑, 内部 max(trade_date) 自动收敛
  - 周末跑 = no-op (max = 6-17 周三, 跟 6-20 周一对比, 缺 6-18/19/20, 但 .day 文件
    周末没新数据, max 还是 6-17, 跑完还是 0 行. 下周一 .day 更新了再补)
  - 节假日同理

用法:
    python scripts/daily_eod_incremental.py
    python scripts/daily_eod_incremental.py --dry-run   # 只看缺几天
    python scripts/daily_eod_incremental.py --no-backfill  # 只跑 limit 回算
    python scripts/daily_eod_incremental.py --no-summary   # 只跑 backfill
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.adapters.market.duckdb_store import conn, get_conn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("daily_eod_incremental")

SCRIPTS = Path(__file__).resolve().parent


def _max_trade_date() -> date | None:
    with conn() as c:
        row = c.execute("SELECT MAX(trade_date) FROM daily_raw").fetchone()
    if row and row[0] is not None:
        v = row[0]
        return v.date() if hasattr(v, "date") else v
    return None


def _max_les_date() -> date | None:
    """max(limit_emotion_summary_daily.trade_date) — 给 skip limit 用."""
    try:
        with conn() as c:
            row = c.execute("SELECT MAX(trade_date) FROM limit_emotion_summary_daily").fetchone()
    except Exception:
        return None
    if row and row[0] is not None:
        v = row[0]
        return v.date() if hasattr(v, "date") else v
    return None


def _run(cmd: list[str], label: str) -> bool:
    print()
    print("=" * 70)
    print(f"  {label}")
    print("=" * 70)
    t0 = time.time()
    try:
        r = subprocess.run([sys.executable, "-u", *cmd], check=False)
    except Exception as exc:  # noqa: BLE001
        log.error("%s crashed: %s: %s", label, type(exc).__name__, exc)
        return False
    el = time.time() - t0
    ok = r.returncode == 0
    log.info("[%s] %s  in %.1fs", Path(cmd[0]).name, "OK" if ok else f"FAIL({r.returncode})", el)
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="每日 EOD 增量入 duckdb")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划, 不执行")
    ap.add_argument("--no-backfill", action="store_true", help="跳过 initial_backfill 步骤")
    ap.add_argument("--no-summary", action="store_true", help="跳过 limit_emotion_summary 步骤")
    ap.add_argument("--no-overview", action="store_true", help="跳过 market_overview_daily 步骤")
    args = ap.parse_args()

    today = date.today()
    log.info("today=%s  dry-run=%s", today.isoformat(), args.dry_run)

    # 1. 当前 max(trade_date)
    max_td = _max_trade_date()
    max_les = _max_les_date()
    log.info("daily_raw max(trade_date)         = %s", max_td)
    log.info("limit_emotion_summary max(td)     = %s", max_les)

    if max_td is None:
        log.warning("daily_raw 是空的, 请先跑 initial_backfill.py 一次性回填")
        return 1

    # 2. 缺几天 (rough, 不算交易日, 只是 calendar days 差)
    gap_days = (today - max_td).days
    if gap_days < 0:
        log.warning("today < max(trade_date)?? %s < %s — 异常, 跳过", today, max_td)
        return 1
    if gap_days == 0:
        log.info("daily_raw 已是今日, 无需 backfill")
        need_backfill = False
    elif gap_days <= 2:
        log.info("差 %d 天 (max=%s, today=%s) — 跑一次 backfill", gap_days, max_td, today)
        need_backfill = True
    else:
        # 差太多 (例如 3 天以上), 大概率是周末 + 节假日
        log.info("差 %d 天 (max=%s, today=%s) — 跑 backfill (INSERT OR IGNORE 幂等)", gap_days, max_td, today)
        need_backfill = True

    # 3. limit_emotion_summary 缺几天 (含今天)
    if max_les is None:
        les_gap = gap_days + 1
    else:
        les_gap = (today - max_les).days
    log.info("limit_emotion_summary 缺 %d 天", les_gap)

    if args.dry_run:
        log.info("[dry-run] 不会执行任何步骤")
        return 0

    ok = True
    if need_backfill and not args.no_backfill:
        ok &= _run(
            [str(SCRIPTS / "initial_backfill.py")],
            "Step 1  initial_backfill.py  (全量重 parse, INSERT OR IGNORE 补齐缺日)",
        )

    if not args.no_summary and les_gap > 0:
        # 留 1 天 buffer 防 weekday 错位
        days = min(les_gap + 2, 60)
        ok &= _run(
            [str(SCRIPTS / "backfill_limit_emotion_summary.py"), f"--days={days}"],
            f"Step 2  backfill_limit_emotion_summary.py --days={days}  (回算 limit 综合分)",
        )

    # Step 3: 大盘概况 / 行业 90 回填 duckdb (双保险, 主调度在 17:10 market_overview_daily_scheduler)
    if not args.no_overview:
        ok &= _run(
            [str(SCRIPTS / "backfill_market_overview_daily.py"), "--days=3"],
            "Step 3  backfill_market_overview_daily.py --days=3  (大盘 / 行业 90 → duckdb)",
        )

    log.info("daily_eod_incremental done.  ok=%s", ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
