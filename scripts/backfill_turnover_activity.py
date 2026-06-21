"""成交活跃度 duckdb 回填脚本.

计算公式: ratio = 当日全市场成交额 / 过去 20 日平均成交额
数据源: duckdb.daily_raw.amount (999999 + 399001 成交额求和, 元→亿元)
目标表: turnover_activity_daily (INSERT OR REPLACE by trade_date)

幂等: 全部走 INSERT OR REPLACE, 重复跑不写脏.

用法:
    python scripts/backfill_turnover_activity.py
    python scripts/backfill_turnover_activity.py --days=60
    python scripts/backfill_turnover_activity.py --start=2026-06-01 --end=2026-06-17
    python scripts/backfill_turnover_activity.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("backfill_turnover_activity")

from backend.adapters.market.duckdb_store import init_schema

_TARGET_TRADE_DATE_ENV = "MINIMAX_TARGET_TRADE_DATE"


def _resolve_end_date() -> date:
    value = (os.environ.get(_TARGET_TRADE_DATE_ENV) or "").strip()
    if not value:
        return date.today()
    return date.fromisoformat(value)


def _bulk_rebuild_turnover_activity(start: date, end: date) -> int:
    """用单次 SQL 批量覆盖重算区间数据，避免逐日开关连接过慢。"""
    from backend.adapters.market.duckdb_store import conn

    with conn(read_only=False) as con:
        con.execute(
            """
            INSERT OR REPLACE INTO turnover_activity_daily
                (trade_date, total_amount, avg_20d_amount, ratio, score,
                 elapsed_ms, source, ingested_at)
            WITH source_dates AS (
                SELECT trade_date,
                       SUM(CASE WHEN code = '999999' THEN amount ELSE 0 END) / 100000000.0 AS sh_amount_yi,
                       SUM(CASE WHEN code = '399001' THEN amount ELSE 0 END) / 100000000.0 AS sz_amount_yi,
                       (SUM(CASE WHEN code = '999999' THEN amount ELSE 0 END)
                        + SUM(CASE WHEN code = '399001' THEN amount ELSE 0 END)) / 100000000.0 AS total_amount_yi
                  FROM daily_raw
                 WHERE trade_date <= ?
                   AND code IN ('999999', '399001')
                 GROUP BY trade_date
                HAVING COUNT(DISTINCT code) = 2
            ),
            enriched AS (
                SELECT trade_date,
                       ROUND(total_amount_yi, 2) AS total_amount,
                       ROUND(
                           AVG(total_amount_yi) OVER (
                               ORDER BY trade_date
                               ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
                           ),
                           2
                       ) AS avg_20d_amount,
                       ROUND(
                           total_amount_yi / NULLIF(
                               AVG(total_amount_yi) OVER (
                                   ORDER BY trade_date
                                   ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
                               ),
                               0
                           ),
                           4
                       ) AS ratio
                  FROM source_dates
            )
            SELECT trade_date,
                   total_amount,
                   avg_20d_amount,
                   ratio,
                   NULL AS score,
                   0 AS elapsed_ms,
                   'duckdb.daily_raw.999999+399001' AS source,
                   current_timestamp
              FROM enriched
             WHERE trade_date BETWEEN ? AND ?
               AND avg_20d_amount IS NOT NULL
               AND ratio IS NOT NULL
            """,
            [end, start, end],
        )
        con.execute(
            """
            UPDATE turnover_activity_daily cur
               SET score = ROUND((
                    SELECT COUNT(*) FILTER (WHERE prev.ratio < cur.ratio) * 100.0
                           / NULLIF(COUNT(*), 0)
                      FROM turnover_activity_daily prev
                     WHERE prev.trade_date >= cur.trade_date - INTERVAL '1060 days'
                       AND prev.trade_date < cur.trade_date
                       AND prev.ratio IS NOT NULL
               ), 1)
             WHERE cur.trade_date BETWEEN ? AND ?
            """,
            [start, end],
        )
        row = con.execute(
            "SELECT COUNT(*) FROM turnover_activity_daily WHERE trade_date BETWEEN ? AND ?",
            [start, end],
        ).fetchone()
    return int(row[0] or 0) if row else 0


def main(argv: list[str] | None = None) -> int:
    """成交活跃度 duckdb 回填入口.

    `argv` 默认 None → 走 sys.argv. 接受 list 给 in-process 调用方传参
    (e.g. daily_eod_incremental 调它, 避免 subprocess 再开 duckdb 撞锁).
    """
    ap = argparse.ArgumentParser(description="成交活跃度 duckdb 回填")
    ap.add_argument("--days", type=int, default=60, help="回填最近 N 天 (默认 60)")
    ap.add_argument("--start", type=str, default=None, help="起始日 YYYY-MM-DD")
    ap.add_argument("--end", type=str, default=None, help="结束日 YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划, 不执行")
    args = ap.parse_args(argv)

    init_schema()

    from backend.adapters.market.duckdb_store import conn
    from backend.repositories.market.turnover_activity_repo import (
        calc_turnover_activity,
        get_turnover_activity_source_coverage,
        get_turnover_activity_source_dates,
        save_turnover_activity,
        _add_score,
    )

    coverage = get_turnover_activity_source_coverage()
    db_min = coverage.get("firstDate")
    db_max = coverage.get("lastDate")
    if db_min is None or db_max is None:
        log.warning("daily_raw 缺少 999999 + 399001 完整成交额数据, 请先确认 TDX 日线已回填")
        return 1

    end_date = _resolve_end_date()
    if args.start:
        start = date.fromisoformat(args.start)
    else:
        start = max(db_min, end_date - timedelta(days=args.days))
    if args.end:
        end = date.fromisoformat(args.end)
    else:
        end = min(db_max, end_date)

    if start > end:
        log.warning("start=%s > end=%s, 无数据可回填", start, end)
        return 0

    trade_dates = get_turnover_activity_source_dates(start, end)
    log.info(
        "daily_raw(999999+399001) 在 %s ~ %s 中共 %d 个交易日 (%s=%s)",
        start,
        end,
        len(trade_dates),
        _TARGET_TRADE_DATE_ENV,
        end_date,
    )
    if args.dry_run:
        log.info("[dry-run] 不会执行写入")
        return 0

    t0 = time.time()
    ok_count = 0
    fail_count = 0
    span_days = (end - start).days + 1
    if span_days >= 120:
        try:
            ok_count = _bulk_rebuild_turnover_activity(start, end)
            log.info("bulk overwrite finished: wrote %d rows", ok_count)
        except Exception as exc:
            log.warning("bulk rebuild failed, fallback to per-day mode: %s", exc)
            fail_count += 1

    if ok_count == 0:
        for td in trade_dates:
            try:
                payload = calc_turnover_activity(td)
                if payload is None:
                    log.debug("  %s 数据不足, 跳过", td)
                    continue
                _add_score(payload, td)
                save_turnover_activity(payload)
                ok_count += 1
            except Exception as exc:
                log.warning("  %s failed: %s", td, exc)
                fail_count += 1
            if ok_count % 20 == 0:
                log.info("  processed %d/%d...", ok_count + fail_count, len(trade_dates))

    elapsed = time.time() - t0
    log.info("done: ok=%d fail=%d in %.1fs", ok_count, fail_count, elapsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
