"""回填 MA 计数 + 宽基指数收益 持久化数据.

用法:
    python scripts/backfill_ma_count_and_returns.py [--days=60] [--force]

数据流:
  - MA 计数: 对 daily_qfq 跑 calc_ma_count(每个交易日) → 落 ma_count_daily
  - 指数收益: 对 5/10/20/60 四个窗口跑 get_index_returns(每个交易日) → 落 index_returns_daily

回填窗口: 从 --days 天前到今天, 跳过周末, 跳过没数据的日 (是周末/节假日或 daily_qfq 缺失).
强制重算: --force 会覆盖已有记录.
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.adapters.market.clickhouse_store import query_one
from backend.config.database import session_scope
from backend.repositories.market.indicator_repo import (
    bulk_calc_ma_count, bulk_save_ma_count,
)
from backend.repositories.market.index_repo import (
    get_index_returns_as_of, save_index_returns,
)
from backend.repositories.market.market_pg_cynexus_repo import qname
from backend.services.stock.trading_calendar import is_trading_day
from sqlalchemy import text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("backfill_metrics")

_TARGET_TRADE_DATE_ENV = "MINIMAX_TARGET_TRADE_DATE"
_REPO_ROOT = Path(__file__).resolve().parents[1]
_FETCH_INDEX_SCRIPT = _REPO_ROOT / "scripts" / "fetch_index_history.py"


def _walk_trading_days(start: date, end: date) -> list[date]:
    """从 start 到 end (含) 之间的所有交易日."""
    out: list[date] = []
    cur = start
    while cur <= end:
        if is_trading_day(cur):
            out.append(cur)
        cur += timedelta(days=1)
    return out


def _resolve_end_date() -> date:
    """优先使用 scheduler 注入的目标交易日; 缺失时回退到今天."""
    target = (os.getenv(_TARGET_TRADE_DATE_ENV) or "").strip()
    if not target:
        return date.today()
    try:
        return date.fromisoformat(target)
    except ValueError:
        log.warning("忽略非法 %s=%r, 回退到 today()", _TARGET_TRADE_DATE_ENV, target)
        return date.today()


def _has_daily_qfq_data(trade_date: date) -> bool:
    """检查 ClickHouse daily_qfq 在指定日是否有数据 (MA 计数前提)."""
    r = query_one("SELECT count() FROM daily_qfq WHERE trade_date = %s", (trade_date,))
    return bool(r and r[0] > 0)


def _has_index_daily_data(trade_date: date) -> bool:
    """检查 ClickHouse index_daily_raw 在指定日是否有 2 只指数的数据."""
    r = query_one(
        "SELECT countDistinct(code) FROM index_daily_raw WHERE trade_date = %s",
        (trade_date,),
    )
    return bool(r and r[0] >= 2)


def _latest_index_daily_date() -> date | None:
    r = query_one(
        "SELECT min(latest_trade_date) FROM ("
        "  SELECT code, max(trade_date) AS latest_trade_date"
        "    FROM index_daily_raw"
        "   WHERE code IN ('sh000001', 'sh000300', 'sh000852')"
        "   GROUP BY code"
        ") t"
    )
    if not r or r[0] is None:
        return None
    v = r[0]
    return v.date() if hasattr(v, "date") else v


def _auto_pull_index_history(days: int = 30) -> None:
    if not _FETCH_INDEX_SCRIPT.exists():
        log.warning("index auto-pull 跳过: fetch_index_history.py 不存在")
        return
    log.info(
        "index auto-pull: %s --days=%d --codes=000001,000300,000852",
        _FETCH_INDEX_SCRIPT.name,
        days,
    )
    try:
        subprocess.run(
            [
                sys.executable,
                str(_FETCH_INDEX_SCRIPT),
                "--days",
                str(days),
                "--codes",
                "000001,000300,000852",
            ],
            check=True,
            cwd=str(_REPO_ROOT),
        )
    except subprocess.CalledProcessError as exc:
        log.warning("index auto-pull 失败: rc=%d", exc.returncode)


def _ma_exists(trade_date: date) -> bool:
    with session_scope() as db:
        r = db.execute(
            text(f"SELECT 1 FROM {qname('msi_ma_count_daily')} WHERE trade_date = :td AND deleted_at IS NULL LIMIT 1"),
            {"td": trade_date},
        ).first()
    return r is not None


def _index_returns_exist(trade_date: date) -> bool:
    with session_scope() as db:
        r = db.execute(
            text(f"SELECT COUNT(DISTINCT window_days) FROM {qname('mkt_index_return_daily')} WHERE trade_date = :td AND deleted_at IS NULL"),
            {"td": trade_date},
        ).first()
    return bool(r and r[0] >= 4)


def main() -> int:
    ap = argparse.ArgumentParser(description="回填 MA 计数 + 指数收益到 PostgreSQL")
    ap.add_argument("--days", type=int, default=60,
                    help="回填窗口天数 (默认 60, 包含周末/节假日, 内部会过滤)")
    ap.add_argument("--force", action="store_true",
                    help="覆盖已有记录 (默认跳过已有)")
    ap.add_argument("--skip-ma", action="store_true",
                    help="跳过 MA 计数 (只跑指数)")
    ap.add_argument("--skip-index", action="store_true",
                    help="跳过指数收益 (只跑 MA)")
    ap.add_argument("--index-windows", type=str, default="5,10,20,60",
                    help="指数收益窗口, 逗号分隔 (默认 5,10,20,60)")
    args = ap.parse_args()

    end_date = _resolve_end_date()
    start = end_date - timedelta(days=args.days)
    windows = [int(x) for x in args.index_windows.split(",") if x.strip()]
    log.info(
        "回填窗口: %s ~ %s, 指数 windows=%s, force=%s, target_env=%s",
        start.isoformat(),
        end_date.isoformat(),
        windows,
        args.force,
        os.getenv(_TARGET_TRADE_DATE_ENV),
    )

    dates = _walk_trading_days(start, end_date)
    log.info("候选交易日 %d 天", len(dates))

    t0 = time.time()
    ma_done = ma_skip = ma_fail = 0
    ir_done = ir_skip = ir_fail = 0

    # ----- MA 计数 (bulk: 一次 SQL 算整个区间) -----
    if not args.skip_ma:
        # 过滤有数据的交易日 (避免无 daily_qfq 的周末/节假日拉低指标)
        candidate_dates = [td for td in dates if _has_daily_qfq_data(td)]
        if not candidate_dates:
            log.info("MA: 无候选交易日, 跳过")
        else:
            if args.force:
                # --force: 强制重算区间内所有日
                target_dates = candidate_dates
            else:
                # 默认跳过已有, 只算缺失的日
                target_dates = [td for td in candidate_dates if not _ma_exists(td)]
                ma_skip = len(candidate_dates) - len(target_dates)
            if not target_dates:
                log.info("MA: 所有 %d 个候选日都已存在, 跳过", len(candidate_dates))
            else:
                try:
                    payloads = bulk_calc_ma_count(
                        min(target_dates), max(target_dates),
                    )
                    # 过滤到 target_dates (windowed SQL 会算整个区间, 包括非 target 的日)
                    payloads = {
                        td: p for td, p in payloads.items() if td in target_dates
                    }
                    bulk_save_ma_count(payloads)
                    ma_done = len(payloads)
                    log.info(
                        "MA: bulk 写入 %d 天 (区间 %s ~ %s, 候选 %d)",
                        ma_done, min(target_dates), max(target_dates),
                        len(candidate_dates),
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("MA bulk 失败: %s", exc)
                    ma_fail = len(target_dates)

    # ----- 指数收益 (单日循环, index_daily_raw 小表 ~ 660 行, 不需要 bulk) -----
    if not args.skip_index:
        latest_index_date = _latest_index_daily_date()
        if (
            end_date in dates
            and (latest_index_date is None or latest_index_date < end_date)
        ):
            log.info(
                "index_daily_raw 最新仅到 %s, 目标=%s, 先补指数历史",
                latest_index_date,
                end_date,
            )
            _auto_pull_index_history(days=max(args.days + 5, 30))

        candidate_dates = [td for td in dates if _has_index_daily_data(td)]
        if not candidate_dates:
            log.info("index: 无候选交易日, 跳过")
        else:
            for td in candidate_dates:
                if not args.force and _index_returns_exist(td):
                    ir_skip += 1
                    continue
                try:
                    for w in windows:
                        items = get_index_returns_as_of(w, td)
                        save_index_returns(w, items)
                    ir_done += 1
                except Exception as exc:  # noqa: BLE001
                    log.warning("index %s 失败: %s", td, exc)
                    ir_fail += 1
            log.info(
                "index: 写入 %d 跳过 %d 失败 %d (候选 %d, windows=%s)",
                ir_done, ir_skip, ir_fail, len(candidate_dates), windows,
            )

    elapsed = time.time() - t0
    log.info(
        "完成: MA 写入 %d 跳过 %d 失败 %d | 指数 写入 %d 跳过 %d 失败 %d | 耗时 %.1fs",
        ma_done, ma_skip, ma_fail, ir_done, ir_skip, ir_fail, elapsed,
    )
    return 0 if not (ma_fail or ir_fail) else 1


if __name__ == "__main__":
    sys.exit(main())
