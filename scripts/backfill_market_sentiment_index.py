"""市场情绪指数 (composite) duckdb 回填脚本.

公式 (v1.0):
  composite_score = 15% × 波动率情绪
                 + 15% × 成交活跃度
                 + 10% × 价格强度 (252 日新高分位)
                 + 10% × 风险偏好
                 + 15% × 市场广度
                 + 15% × 涨跌停情绪
                 + 10% × 赚钱效应
                 +  5% × 板块扩散
                 +  5% × 风格风险偏好

数据源: 各 *_daily 子表 (8 张 sub-card 都要先 backfill 好, 才能拿到完整 composite)
目标表: market_sentiment_index_daily (INSERT OR REPLACE by trade_date)

用法:
    python scripts/backfill_market_sentiment_index.py
    python scripts/backfill_market_sentiment_index.py --days=365
    python scripts/backfill_market_sentiment_index.py --start=2025-06-01 --end=2026-06-17
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("backfill_market_sentiment_index")

from backend.adapters.market.duckdb_store import init_schema, get_conn


# 8 张 sub-card 的 trade_date 来源 (选取 schema §24 公式里的 9 个 component 的底层表)
# 同一日 9 个 component 不一定全有, calc 内部把缺失视为 50 (中性)
_SUB_CARD_TABLES = [
    "volatility_sentiment_daily",
    "turnover_activity_daily",
    "ma_count_daily",            # 价强 + 广度都来自这
    "risk_appetite_daily",
    "limit_emotion_summary_daily",
    "profit_effect_daily",
    "market_pulse_sector_breadth_daily",
    "style_risk_appetite_daily",
]


def main() -> int:
    ap = argparse.ArgumentParser(description="市场情绪指数 duckdb 回填")
    ap.add_argument("--days", type=int, default=365, help="回填最近 N 天 (默认 365)")
    ap.add_argument("--start", type=str, default=None, help="起始日 YYYY-MM-DD")
    ap.add_argument("--end", type=str, default=None, help="结束日 YYYY-MM-DD (默认今天)")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划, 不执行")
    ap.add_argument("--force", action="store_true", help="跳过 cache 强制重算")
    args = ap.parse_args()

    init_schema()

    con = get_conn()

    # 收集所有 sub-card 表的并集交易日, 再取窗口
    today = date.today()
    if args.end:
        end = date.fromisoformat(args.end)
    else:
        end = today
    if args.start:
        start = date.fromisoformat(args.start)
    else:
        start = end - timedelta(days=args.days)

    # 找各 sub-card 表的覆盖范围, 取 min / max
    log.info("=== sub-card coverage ===")
    db_min = end
    db_max = start
    for tbl in _SUB_CARD_TABLES:
        try:
            r = con.execute(f"SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM {tbl}").fetchone()
        except Exception as exc:
            log.warning("  %s: skip (%s)", tbl, exc)
            continue
        if not r or r[0] is None:
            log.info("  %-32s EMPTY", tbl)
            continue
        mn = r[0].date() if hasattr(r[0], "date") else r[0]
        mx = r[1].date() if hasattr(r[1], "date") else r[1]
        log.info("  %-32s %s ~ %s  (%d rows)", tbl, mn, mx, int(r[2] or 0))
        if mn < db_min:
            db_min = mn
        if mx > db_max:
            db_max = mx

    if db_min > db_max:
        log.error("无 sub-card 数据, 请先 backfill 各子卡 (profit_effect / risk_appetite / ...)")
        return 1

    # 跟用户给的窗口取交集
    actual_start = max(start, db_min)
    actual_end = min(end, db_max)
    if actual_start > actual_end:
        log.error("窗口为空: user[%s..%s] ∩ db[%s..%s] = ∅", start, end, db_min, db_max)
        return 0
    log.info("窗口: %s ~ %s (用户 [%s..%s] ∩ sub-card [%s..%s])",
             actual_start, actual_end, start, end, db_min, db_max)

    # 收集窗口内所有 (任一 sub-card 有数据的) 交易日
    union_dates: set[date] = set()
    for tbl in _SUB_CARD_TABLES:
        try:
            rows = con.execute(
                f"SELECT DISTINCT trade_date FROM {tbl} "
                f"WHERE trade_date BETWEEN ? AND ?",
                [actual_start, actual_end],
            ).fetchall()
        except Exception:
            continue
        for r in rows:
            d = r[0].date() if hasattr(r[0], "date") else r[0]
            union_dates.add(d)

    trade_dates = sorted(union_dates)
    log.info("共 %d 个交易日 (子卡并集)", len(trade_dates))
    if args.dry_run:
        return 0

    from backend.repositories.market.market_sentiment_index_repo import (
        calc_market_sentiment_index,
        save_market_sentiment_index,
        calc_market_sentiment_index_cached,
    )

    ok_count = fail_count = 0
    full_count = 0    # component_count == 9 (全 9 个 component 都有)
    t0 = time.time()
    for i, td in enumerate(trade_dates):
        try:
            if args.force:
                payload = calc_market_sentiment_index(td)
                if payload:
                    save_market_sentiment_index(payload)
            else:
                payload = calc_market_sentiment_index_cached(td, force=True)
            if payload:
                ok_count += 1
                if payload.get("componentCount") == 9:
                    full_count += 1
            else:
                fail_count += 1
        except Exception as exc:
            log.warning("  %s failed: %s", td, exc)
            fail_count += 1
        if (i + 1) % 100 == 0:
            log.info("  [%d/%d] ok=%d fail=%d full=%d", i + 1, len(trade_dates), ok_count, fail_count, full_count)

    elapsed = time.time() - t0
    log.info("done: ok=%d fail=%d full(9/9)=%d in %.1fs", ok_count, fail_count, full_count, elapsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
