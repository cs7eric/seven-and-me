"""每日 EOD 增量入 duckdb 编排器 (供 17:00 scheduler 调用).

逻辑:
  1. 查 duckdb daily_raw 当前最大 trade_date
  2. 与今天对比, 缺 N 天 → 调 initial_backfill.py (INSERT OR IGNORE 幂等,
     重复跑不会写脏数据, 会自动补齐缺的日期)
  3. 跑完 → 调 backfill_limit_emotion_summary.py --days=N+2 回算
     缺日的 limit_emotion_summary_daily (涨跌停情绪综合分)
  4. qfq/hfq 对账: 找 daily_raw 有但 daily_qfq/hfq 缺的 trade_date, 逐日
     调 fetch_one_date_eltdx.py 补拉 (防 daily_eod step 2 漏跑导致 last day 没 qfq)
  5. backfill_market_overview_daily (大盘 / 行业 90)

跟 daily_eod.py 区别:
  - daily_eod.py 跑全套 8 步 (qfq/hfq/validate/MA 计数等), 是手动一次性
  - 这个脚本只跑"补数据 + 对账 + limit 缓存"几件事, 快, 适合每天 17:00

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
    python scripts/daily_eod_incremental.py --no-qfq       # 跳过 qfq/hfq 对账
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


def _missing_qfq_dates() -> list[date]:
    """找 daily_raw 有但 daily_qfq 缺的 trade_date (近 14 天窗口).

    防御 daily_eod step 2 漏跑导致 "last day 0 行" 局面 (2026-06-17 出现过).
    14 天窗口足够覆盖周末 + 节假日 + 1-2 天 scheduler 漏跑.
    """
    try:
        with conn() as c:
            rows = c.execute("""
                SELECT trade_date
                  FROM (
                    SELECT DISTINCT trade_date
                      FROM daily_raw
                     WHERE trade_date >= current_date - INTERVAL 14 DAY
                  ) r
                  ANTI JOIN (
                    SELECT DISTINCT trade_date
                      FROM daily_qfq
                     WHERE trade_date >= current_date - INTERVAL 14 DAY
                  ) q USING (trade_date)
                 ORDER BY trade_date
            """).fetchall()
    except Exception as exc:
        log.warning("查 missing qfq dates 失败: %s", exc)
        return []
    out = []
    for r in rows:
        v = r[0]
        out.append(v.date() if hasattr(v, "date") else v)
    return out


def _missing_hfq_dates() -> list[date]:
    """同上, daily_hfq."""
    try:
        with conn() as c:
            rows = c.execute("""
                SELECT trade_date
                  FROM (
                    SELECT DISTINCT trade_date
                      FROM daily_raw
                     WHERE trade_date >= current_date - INTERVAL 14 DAY
                  ) r
                  ANTI JOIN (
                    SELECT DISTINCT trade_date
                      FROM daily_hfq
                     WHERE trade_date >= current_date - INTERVAL 14 DAY
                  ) h USING (trade_date)
                 ORDER BY trade_date
            """).fetchall()
    except Exception as exc:
        log.warning("查 missing hfq dates 失败: %s", exc)
        return []
    out = []
    for r in rows:
        v = r[0]
        out.append(v.date() if hasattr(v, "date") else v)
    return []


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
    ap.add_argument("--no-turnover", action="store_true", help="跳过成交活跃度回填步骤")
    ap.add_argument("--no-qfq", action="store_true", help="跳过 qfq/hfq 对账步骤")
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

    # 4. qfq/hfq 对账: 找 daily_raw 有但 qfq/hfq 缺的 trade_date
    missing_qfq = _missing_qfq_dates() if not args.no_qfq else []
    missing_hfq = _missing_hfq_dates() if not args.no_qfq else []
    # 取并集, 一次 fetch_one_date_eltdx 跑 (脚本内部同时跑 qfq + hfq)
    missing_adj = sorted(set(missing_qfq) | set(missing_hfq))
    log.info("qfq 缺 %d 天: %s", len(missing_qfq),
             [d.isoformat() for d in missing_qfq[-5:]])
    log.info("hfq 缺 %d 天: %s", len(missing_hfq),
             [d.isoformat() for d in missing_hfq[-5:]])
    log.info("qfq/hfq 合并缺 %d 天 (近 14 天窗口)", len(missing_adj))

    if args.dry_run:
        log.info("[dry-run] 不会执行任何步骤")
        return 0

    ok = True
    if need_backfill and not args.no_backfill:
        ok &= _run(
            [str(SCRIPTS / "initial_backfill.py")],
            "Step 1  initial_backfill.py  (全量重 parse, INSERT OR IGNORE 补齐缺日)",
        )

    if not args.no_qfq and missing_adj:
        # 逐日 in-process 调 fetch_one_date_eltdx.run() (避免 subprocess 的 duckdb 文件锁冲突)
        from scripts.fetch_one_date_eltdx import run as _run_fetch_adj
        for td in missing_adj:
            td_str = td.isoformat()
            print()
            print("=" * 70)
            print(f"  Step 2  fetch_one_date_eltdx --date={td_str} (qfq/hfq 对账补拉)")
            print("=" * 70)
            t0 = time.time()
            try:
                result = _run_fetch_adj(date_str=td_str, adjust="both", workers=32)
                el = time.time() - t0
                qfq_n = result.get("qfq_rows", 0)
                hfq_n = result.get("hfq_rows", 0)
                err_n = result.get("errors", 0)
                log.info("[fetch_one_date_eltdx.%s] qfq=%d hfq=%d err=%d  in %.1fs",
                         td_str, qfq_n, hfq_n, err_n, el)
            except Exception as exc:
                log.error("fetch_adj %s crashed: %s: %s", td_str, type(exc).__name__, exc)
                ok = False

    if not args.no_summary and les_gap > 0:
        # 留 1 天 buffer 防 weekday 错位
        days = min(les_gap + 2, 60)
        ok &= _run(
            [str(SCRIPTS / "backfill_limit_emotion_summary.py"), f"--days={days}"],
            f"Step 3  backfill_limit_emotion_summary.py --days={days}  (回算 limit 综合分)",
        )

    # Step 4: 大盘概况 / 行业 90 回填 duckdb (双保险, 主调度在 17:10 market_overview_daily_scheduler)
    if not args.no_overview:
        ok &= _run(
            [str(SCRIPTS / "backfill_market_overview_daily.py"), "--days=3"],
            "Step 4  backfill_market_overview_daily.py --days=3  (大盘 / 行业 90 → duckdb)",
        )

    # Step 5: 成交活跃度回填 duckdb (市场温度指标)
    if not args.no_turnover:
        ok &= _run(
            [str(SCRIPTS / "backfill_turnover_activity.py"), "--days=3"],
            "Step 5  backfill_turnover_activity.py --days=3  (成交活跃度 → duckdb)",
        )

    log.info("daily_eod_incremental done.  ok=%s", ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
