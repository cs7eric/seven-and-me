"""回填 volatility_sentiment_daily.

用法:
    python scripts/backfill_volatility_sentiment.py [--days=60] [--force] [--auto-pull]
    python scripts/backfill_volatility_sentiment.py --date=2026-06-16
    python scripts/backfill_volatility_sentiment.py --dry-run

数据流:
  沪深300 (sh000300) 近 20 日日收益率 std × √252 → vol
  近 252 日 vol 滚动分位 → 1 - percentile → 情绪得分 0-100
  走 duckdb.index_daily_raw (有完整历史, 5200+ 行, 但只用了最近 ~280)

回填窗口: 从 --days 天前到今天, 跳过周末/节假日 (无 index_daily_raw 数据).
强制重算: --force 会覆盖已有记录 (calc_volatility_sentiment_cached(..., force=True)).

依赖:
  至少 lookback + window + 10 = 282 天的 index_daily_raw 数据 (默认 252 + 20 + 10).
  --auto-pull 自动调 fetch_index_history.py --days=300 补数据 (单次, 默认开启).
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

from backend.adapters.market.duckdb_store import get_conn
from backend.repositories.market.volatility_sentiment_repo import (
    DEFAULT_VOL_LOOKBACK,
    DEFAULT_VOL_WINDOW,
    calc_volatility_sentiment_cached,
    coverage,
)
from backend.services.stock.trading_calendar import is_trading_day

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("backfill_volatility_sentiment")

REPO_ROOT = Path(__file__).resolve().parents[1]
FETCH_SCRIPT = REPO_ROOT / "scripts" / "fetch_index_history.py"


# 标的固定: 沪深300 (跟 repo 默认对齐). 改这里即可.
UNDERLYING = {"code": "000300", "name": "沪深300", "full": "sh000300"}


def _index_row_count() -> int:
    con = get_conn()
    r = con.execute(
        "SELECT COUNT(*) FROM index_daily_raw WHERE code = ?",
        [UNDERLYING["full"]],
    ).fetchone()
    return int(r[0]) if r else 0


def _auto_pull_index_history(days: int = 300) -> None:
    """数据不足时自动拉一次 (走 fetch_index_history.py 子进程)."""
    if not FETCH_SCRIPT.exists():
        log.warning("  fetch_index_history.py 不存在, 跳过 auto-pull")
        return
    log.info("  auto-pull: %s --days=%d --codes=%s",
             FETCH_SCRIPT.name, days, UNDERLYING["code"])
    try:
        subprocess.run(
            [sys.executable, str(FETCH_SCRIPT), "--days", str(days),
             "--codes", UNDERLYING["code"]],
            check=True,
            cwd=str(REPO_ROOT),
        )
    except subprocess.CalledProcessError as exc:
        log.warning("  auto-pull 失败: rc=%d", exc.returncode)


def _vs_exists(trade_date: date) -> bool:
    con = get_conn()
    r = con.execute(
        "SELECT 1 FROM volatility_sentiment_daily WHERE trade_date = ?", [trade_date]
    ).fetchone()
    return r is not None


def _walk_trading_days(start: date, end: date) -> list[date]:
    out: list[date] = []
    cur = start
    while cur <= end:
        if is_trading_day(cur):
            out.append(cur)
        cur += timedelta(days=1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="回填 volatility_sentiment_daily 到 duckdb")
    ap.add_argument("--days", type=int, default=60,
                    help="回填窗口天数 (默认 60, 内部过滤非交易日)")
    ap.add_argument("--date", type=str, default=None,
                    help="单日 YYYY-MM-DD, 跟 --days 互斥")
    ap.add_argument("--force", action="store_true", help="覆盖已有记录")
    ap.add_argument("--auto-pull", dest="auto_pull", action="store_true", default=True,
                    help="数据不足时自动拉指数历史 (默认开启)")
    ap.add_argument("--no-auto-pull", dest="auto_pull", action="store_false",
                    help="关闭自动拉数")
    ap.add_argument("--dry-run", action="store_true", help="不写库, 只打印会跑哪些日")
    args = ap.parse_args()

    # 1. 数据充足性检查
    min_rows = DEFAULT_VOL_LOOKBACK + DEFAULT_VOL_WINDOW + 10  # 282
    have = _index_row_count()
    log.info("index_daily_raw[%s] 现有 %d 行 (最少 %d)", UNDERLYING["full"], have, min_rows)
    if have < min_rows:
        if args.auto_pull:
            _auto_pull_index_history(days=300)
            have = _index_row_count()
            log.info("  auto-pull 后: %d 行", have)
        else:
            log.warning("  数据不足且关闭 auto-pull, 回填出来的 vol 仍可用, "
                        "但 percentile 样本数会少")

    # 2. 构造候选日
    if args.date:
        try:
            target = date.fromisoformat(args.date)
        except ValueError as exc:
            log.error("无效 --date: %s", exc)
            return 1
        dates = [target]
        log.info("单日模式: %s", target.isoformat())
    else:
        today = date.today()
        start = today - timedelta(days=args.days)
        dates = _walk_trading_days(start, today)
        log.info("回填窗口: %s ~ %s, 候选交易日 %d 天, force=%s",
                 start.isoformat(), today.isoformat(), len(dates), args.force)

    if args.dry_run:
        log.info("[dry-run] 候选日: %s", [d.isoformat() for d in dates[:10]])
        log.info("[dry-run] 没写任何东西")
        return 0

    # 3. 回填
    t0 = time.time()
    done = skip = fail = 0
    for i, td in enumerate(dates):
        if not args.force and _vs_exists(td):
            skip += 1
            continue
        try:
            payload = calc_volatility_sentiment_cached(td, force=args.force)
            if payload is None:
                log.debug("  %s 跳过 (无 vol)", td)
                continue
            done += 1
            log.info("[%d/%d] %s 落盘: vol=%.2f%%  pct=%.4f  score=%.1f",
                     i + 1, len(dates), td,
                     payload["realizedVol20d"],
                     payload["percentile1y"],
                     payload["sentimentScore"])
        except Exception as exc:  # noqa: BLE001
            log.warning("  %s 失败: %s", td, exc)
            fail += 1

    elapsed = time.time() - t0
    log.info("完成: 写入 %d 跳过 %d 失败 %d | 耗时 %.1fs",
             done, skip, fail, elapsed)
    log.info("coverage: %s", coverage())
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
