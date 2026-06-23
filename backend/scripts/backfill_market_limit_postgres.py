r"""Backfill limit emotion snapshots into PostgreSQL.

维护前请先看:
`F:\dev-repo\mp4-to-word-new\design\backend\limit-emotion-json-to-postgres.md`

用法:
    python -m backend.scripts.backfill_market_limit_postgres

逻辑:
    1. 读 ``reference/market-pulse/snapshots/*/*.json`` (每日最新一份 snapshot)
    2. 读 ``reference/market-limit/daily/<date>.json`` (补 stock_count)
    3. 合并 upsert 到 PG ``app.market_limit_daily_snapshots``
    4. 统计覆盖度
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from backend.config.database import session_scope  # noqa: E402
from backend.config.settings import (  # noqa: E402
    MARKET_LIMIT_DAILY_DIR,
    MARKET_PULSE_LIMIT_SNAPSHOTS_DIR,
)
from backend.repositories.market.market_limit_pg_repo import (  # noqa: E402
    MarketLimitPgRepository,
)

logger = logging.getLogger(__name__)


def _yyyymmdd_to_date(stem: str) -> date | None:
    if len(stem) != 8 or not stem.isdigit():
        return None
    try:
        return date(int(stem[:4]), int(stem[4:6]), int(stem[6:8]))
    except ValueError:
        return None


def _extract_summary(payload: dict) -> dict:
    """从 full computed payload 提取摘要字段."""
    limit_up = payload.get("limitUp") or {}
    limit_down = payload.get("limitDown") or {}
    break_board = payload.get("breakBoard") or {}
    streak = payload.get("streak") or {}
    meta = payload.get("_meta") or {}

    fields: dict = {
        "limit_up_count": limit_up.get("count"),
        "limit_down_count": limit_down.get("count"),
        "touched_count": break_board.get("touchedCount"),
        "broken_count": break_board.get("brokenCount"),
        "break_board_rate": break_board.get("rate"),
        "max_streak_height": streak.get("maxHeight"),
        "promotion_overall_rate": streak.get("promotion", {}).get("overallRate"),
        "sentiment_level": streak.get("sentiment", {}).get("level"),
        "sentiment_text": streak.get("sentiment", {}).get("text"),
        "stock_count": meta.get("stockCount"),
        "market_status": payload.get("marketStatus"),
        "data_status": payload.get("dataStatus") or meta.get("dataStatus"),
        "source": meta.get("source"),
    }
    return {k: v for k, v in fields.items() if v is not None}


def backfill_from_snapshots(repo: MarketLimitPgRepository, *, force: bool = False) -> int:
    """从 market-pulse/snapshots/** 回填 (每日取最新一份).

    Args:
        repo: repository
        force: 强制重新写入 (含 stocks)
    """
    count = 0
    if not MARKET_PULSE_LIMIT_SNAPSHOTS_DIR.exists():
        logger.warning("snapshots dir not found: %s", MARKET_PULSE_LIMIT_SNAPSHOTS_DIR)
        return 0

    from backend.services.stock._limit_pg_writer import (  # noqa: PLC0415
        _extract_stocks_from_payload,
    )

    # 按日期目录遍历
    date_dirs = sorted(
        d for d in MARKET_PULSE_LIMIT_SNAPSHOTS_DIR.iterdir() if d.is_dir()
    )
    for d in date_dirs:
        try:
            trade_date = date.fromisoformat(d.name)
        except (ValueError, TypeError):
            continue

        # 取该日期最新一份 snapshot
        snap_files = sorted(d.glob("*.json"))
        if not snap_files:
            continue

        try:
            payload = json.loads(snap_files[-1].read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("read %s failed: %s", snap_files[-1], exc)
            continue

        if not isinstance(payload, dict):
            continue

        # 提取股票明细 (即使 summary 已存在也要写 stocks)
        stock_rows = _extract_stocks_from_payload(payload)
        if stock_rows:
            try:
                repo.upsert_stocks(trade_date=trade_date, stocks=stock_rows)
            except Exception as exc:
                logger.warning("upsert_stocks for %s failed: %s", trade_date, exc)

        # 跳过已有 summary 的日期 (除非 force)
        if not force and repo.has_trade_date(trade_date):
            continue

        fields = _extract_summary(payload)
        if not fields:
            continue

        source_tag = fields.pop("source", "unknown") or "unknown"
        repo.upsert(
            trade_date=trade_date,
            fields=fields,
            source_tag=source_tag,
            extra_payload=payload,
        )
        count += 1

    return count


def backfill_from_daily(repo: MarketLimitPgRepository) -> int:
    """从 market-limit/daily/*.json 补充 stock_count 字段."""
    count = 0
    if not MARKET_LIMIT_DAILY_DIR.exists():
        logger.warning("daily dir not found: %s", MARKET_LIMIT_DAILY_DIR)
        return 0

    for path in sorted(MARKET_LIMIT_DAILY_DIR.glob("*.json")):
        stem = path.stem  # YYYY-MM-DD
        try:
            trade_date = date.fromisoformat(stem)
        except (ValueError, TypeError):
            continue

        # 只补已有行 (snapshots 没覆盖到的日期)
        existing = repo.get(trade_date)
        if existing and existing.get("stock_count") is not None:
            continue
        if existing and existing.get("stock_count") is None:
            # 只补 stock_count
            try:
                daily = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(daily, dict):
                    sc = daily.get("stockCount")
                    if sc is not None:
                        repo.upsert(
                            trade_date=trade_date,
                            fields={"stock_count": sc},
                            source_tag="daily_archive",
                            extra_payload=None,
                        )
                        count += 1
            except Exception:
                continue

    return count


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    with session_scope() as db:
        repo = MarketLimitPgRepository(db)

        logger.info("Starting market limit backfill...")

        snap_count = backfill_from_snapshots(repo)
        logger.info("Imported %d days from snapshots", snap_count)

        daily_count = backfill_from_daily(repo)
        logger.info("Updated %d days from daily (stock_count)", daily_count)

        coverage = repo.coverage()
        logger.info(
            "Coverage: %s ~ %s, %d rows",
            coverage["first_date"], coverage["last_date"], coverage["row_count"],
        )

    logger.info("Backfill complete.")


if __name__ == "__main__":
    main()
