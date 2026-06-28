"""每日 EOD 增量编排器 (供 17:00 scheduler 调用).

逻辑:
  1. 查 ClickHouse daily_raw 当前最大 trade_date
  2. 与今天对比, 缺 N 天 → in-process 调 initial_backfill (CH delete+insert 幂等,
     重复跑不会写脏数据, 会自动补齐缺的日期)
  3. qfq/hfq 对账: 找 daily_raw 有但 daily_qfq/hfq 缺的 trade_date, 逐日
     in-process 调 fetch_one_date_eltdx (防 daily_eod step 2 漏跑导致 last day 没 qfq)
  4. in-process 调 backfill_market_overview_daily (大盘 / 行业 90)
  5. in-process 调 backfill_turnover_activity (成交活跃度)

in-process 调用保留为兼容旧脚本 main(argv) 入口; 数据读写已迁到 ClickHouse/PostgreSQL.

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
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.adapters.market.clickhouse_store import query_one, query_rows

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("daily_eod_incremental")

SCRIPTS = Path(__file__).resolve().parent


def _max_trade_date() -> date | None:
    row = query_one("SELECT MAX(trade_date) FROM daily_raw")
    if row and row[0] is not None:
        v = row[0]
        return v.date() if hasattr(v, "date") else v
    return None


def _missing_qfq_dates() -> list[date]:
    """找 daily_raw 有但 daily_qfq 缺的 trade_date (近 14 天窗口)."""
    try:
        rows = query_rows("""
            SELECT trade_date
              FROM (
                    SELECT DISTINCT trade_date
                      FROM daily_raw
                     WHERE trade_date >= today() - 14
                   ) r
             WHERE trade_date NOT IN (
                    SELECT DISTINCT trade_date
                      FROM daily_qfq
                     WHERE trade_date >= today() - 14
                   )
             ORDER BY trade_date
        """)
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
        rows = query_rows("""
            SELECT trade_date
              FROM (
                    SELECT DISTINCT trade_date
                      FROM daily_raw
                     WHERE trade_date >= today() - 14
                   ) r
             WHERE trade_date NOT IN (
                    SELECT DISTINCT trade_date
                      FROM daily_hfq
                     WHERE trade_date >= today() - 14
                   )
             ORDER BY trade_date
        """)
    except Exception as exc:
        log.warning("查 missing hfq dates 失败: %s", exc)
        return []
    out = []
    for r in rows:
        v = r[0]
        out.append(v.date() if hasattr(v, "date") else v)
    return out


def _run_in_process(label: str, fn, argv) -> bool:
    """In-process 调子脚本 main(argv).

    返回: True=OK, False=FAIL.
    """
    print()
    print("=" * 70)
    print(f"  {label}")
    print("=" * 70)
    t0 = time.time()
    try:
        rc = fn(argv) if argv is not None else fn()
        el = time.time() - t0
        ok = (rc == 0 or rc is None)
        log.info("[%s] %s  in %.1fs (rc=%s)", fn.__module__, "OK" if ok else f"FAIL(rc={rc})", el, rc)
        return ok
    except SystemExit as exc:
        el = time.time() - t0
        rc = exc.code
        ok = (rc == 0 or rc is None)
        log.info("[%s] SystemExit %s  in %.1fs", fn.__module__, "OK" if ok else f"FAIL(rc={rc})", el)
        return ok
    except Exception as exc:  # noqa: BLE001
        el = time.time() - t0
        log.error("%s crashed: %s: %s", label, type(exc).__name__, exc)
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="每日 EOD 增量编排")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划, 不执行")
    ap.add_argument("--no-backfill", action="store_true", help="跳过 initial_backfill 步骤")
    ap.add_argument("--no-overview", action="store_true", help="跳过 market_overview_daily 步骤")
    ap.add_argument("--no-turnover", action="store_true", help="跳过成交活跃度回填步骤")
    ap.add_argument("--no-qfq", action="store_true", help="跳过 qfq/hfq 对账步骤")
    args = ap.parse_args()

    # today 默认 date.today(), 但 scheduler 调度时 (周末/节假日 cron 触发)
    # 会通过环境变量 MINIMAX_TARGET_TRADE_DATE 传入上一个交易日, 这里优先用 env.
    import os as _os
    env_target = _os.environ.get("MINIMAX_TARGET_TRADE_DATE")
    if env_target:
        try:
            today = date.fromisoformat(env_target)
            log.info("today (from MINIMAX_TARGET_TRADE_DATE env)=%s", today.isoformat())
        except ValueError:
            log.warning(
                "MINIMAX_TARGET_TRADE_DATE=%s 不是合法 ISO 日期, 回退 date.today()",
                env_target,
            )
            today = date.today()
    else:
        today = date.today()
    log.info("today=%s  dry-run=%s", today.isoformat(), args.dry_run)

    # 1. 当前 max(trade_date)
    max_td = _max_trade_date()
    log.info("daily_raw max(trade_date)         = %s", max_td)

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
        log.info("差 %d 天 (max=%s, today=%s) — 跑 backfill (CH delete+insert 幂等)", gap_days, max_td, today)
        need_backfill = True

    # 3. qfq/hfq 对账: 找 daily_raw 有但 qfq/hfq 缺的 trade_date
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

    # ── Step 1: initial_backfill (ClickHouse daily_raw) ──
    if need_backfill and not args.no_backfill:
        from scripts import initial_backfill as _initial_backfill_mod
        ok &= _run_in_process(
            "Step 1  initial_backfill.main()  (全量重 parse, CH daily_raw 补齐缺日)",
            _initial_backfill_mod.main,
            [],  # argv=[], 用 default 参数
        )

    # ── Step 2: qfq/hfq 对账 (in-process, 逐日) ──
    if not args.no_qfq and missing_adj:
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

    # ── Step 3: 大盘概况 / 行业 90 (in-process) ──
    if not args.no_overview:
        from scripts import backfill_market_overview_daily as _movd_mod
        ok &= _run_in_process(
            f"Step 3  backfill_market_overview_daily.main() --days=3  (大盘 / 行业 90)",
            _movd_mod.main,
            ["--days=3"],
        )

    # ── Step 4: 成交活跃度 (in-process) ──
    if not args.no_turnover:
        from scripts import backfill_turnover_activity as _ta_mod
        ok &= _run_in_process(
            "Step 4  backfill_turnover_activity.main() --days=3  (成交活跃度 → PG)",
            _ta_mod.main,
            ["--days=3"],
        )

    log.info("daily_eod_incremental done.  ok=%s", ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
