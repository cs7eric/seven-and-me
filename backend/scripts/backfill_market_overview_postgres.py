r"""Backfill market overview JSON archives into PostgreSQL.

维护前请先看:
`F:\dev-repo\mp4-to-word-new\design\backend\market-overview-json-to-postgres.md`

用法:
    python -m backend.scripts.backfill_market_overview_postgres

逻辑:
    1. 读 ``reference/market-overview/archive/*.json`` (akshare + merged manual)
    2. 读 ``reference/market-overview/market-overview/archive/*.json`` (eltdx)
    3. 合并 upsert 到 PG ``app.market_overview_snapshots``
    4. 统计覆盖度
"""
from __future__ import annotations

import logging
import sys
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from backend.config.database import session_scope
from backend.config.settings import MARKET_OVERVIEW_ARCHIVE_DIR
from backend.repositories.market.market_overview_pg_repo import MarketOverviewPgRepository
from backend.utils.json_io import read_json_file

logger = logging.getLogger(__name__)

# eltdx archive dir: reference/market-overview/market-overview/archive/
_ELTDX_ARCHIVE_DIR = MARKET_OVERVIEW_ARCHIVE_DIR.parent / "market-overview" / "archive"

# 字段映射: JSON camelCase → PG snake_case
_FIELD_MAP_COMMON = {
    "totalAmount": "total_amount",
    "totalVolume": "total_volume",
    "risingCount": "rising_count",
    "fallingCount": "falling_count",
    "flatCount": "flat_count",
    "limitUpCount": "limit_up_count",
    "limitDownCount": "limit_down_count",
    "stockCount": "stock_count",
    "mainNetInflow": "main_net_inflow",
    "mainNetInflowRatio": "main_net_inflow_ratio",
    "superLargeNetInflow": "super_large_net_inflow",
    "superLargeNetInflowRatio": "super_large_net_ratio",
    "largeNetInflow": "large_net_inflow",
    "largeNetInflowRatio": "large_net_ratio",
    "mediumNetInflow": "medium_net_inflow",
    "mediumNetInflowRatio": "medium_net_ratio",
    "smallNetInflow": "small_net_inflow",
    "smallNetInflowRatio": "small_net_ratio",
}


def _yyyymmdd_to_date(stem: str) -> date | None:
    if len(stem) != 8 or not stem.isdigit():
        return None
    try:
        return date(int(stem[:4]), int(stem[4:6]), int(stem[6:8]))
    except ValueError:
        return None


def _map_fields(payload: dict) -> dict:
    """Convert JSON camelCase keys to snake_case."""
    result = {}
    for camel, snake in _FIELD_MAP_COMMON.items():
        v = payload.get(camel)
        if v is not None:
            result[snake] = v
    return result


def backfill_from_archive(repo: MarketOverviewPgRepository) -> int:
    """Import shared archive (akshare + merged manual)."""
    count = 0
    if not MARKET_OVERVIEW_ARCHIVE_DIR.exists():
        logger.warning("shared archive dir not found: %s", MARKET_OVERVIEW_ARCHIVE_DIR)
        return 0

    for path in sorted(MARKET_OVERVIEW_ARCHIVE_DIR.glob("*.json")):
        trade_date = _yyyymmdd_to_date(path.stem)
        if trade_date is None:
            continue
        if repo.has_trade_date(trade_date):
            continue

        payload = read_json_file(path, {})
        if not isinstance(payload, dict):
            continue

        fields = _map_fields(payload)
        if not fields:
            continue

        # Determine source tag from original data
        src = (payload.get("source") or "").lower()
        if "manual" in src:
            source_tag = "manual"
        else:
            source_tag = "akshare"

        repo.upsert(trade_date=trade_date, fields=fields, source_tag=source_tag)
        count += 1

    return count


def backfill_from_eltdx(repo: MarketOverviewPgRepository) -> int:
    """Import eltdx archive (totalAmount / risingCount / fallingCount only)."""
    count = 0
    if not _ELTDX_ARCHIVE_DIR.exists():
        logger.warning("eltdx archive dir not found: %s", _ELTDX_ARCHIVE_DIR)
        return 0

    for path in sorted(_ELTDX_ARCHIVE_DIR.glob("*.json")):
        trade_date = _yyyymmdd_to_date(path.stem)
        if trade_date is None:
            continue

        payload = read_json_file(path, {})
        if not isinstance(payload, dict):
            continue

        # eltdx 贡献: 大盘成交额 + 涨跌家数 + 涨停跌停
        eltdx_fields = {}
        for camel, snake in [
            ("totalAmount", "total_amount"),
            ("totalVolume", "total_volume"),
            ("risingCount", "rising_count"),
            ("fallingCount", "falling_count"),
            ("flatCount", "flat_count"),
            ("limitUpCount", "limit_up_count"),
            ("limitDownCount", "limit_down_count"),
            ("stockCount", "stock_count"),
        ]:
            v = payload.get(camel)
            if v is not None:
                eltdx_fields[snake] = v

        if not eltdx_fields:
            continue

        repo.upsert(trade_date=trade_date, fields=eltdx_fields, source_tag="eltdx")
        count += 1

    return count


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    with session_scope() as db:
        repo = MarketOverviewPgRepository(db)

        logger.info("Starting market overview backfill...")

        akshare_count = backfill_from_archive(repo)
        logger.info("Imported %d days from shared archive", akshare_count)

        eltdx_count = backfill_from_eltdx(repo)
        logger.info("Imported %d days from eltdx archive", eltdx_count)

        coverage = repo.coverage()
        logger.info(
            "Coverage: %s ~ %s, %d rows",
            coverage["first_date"], coverage["last_date"], coverage["row_count"],
        )

    logger.info("Backfill complete.")


if __name__ == "__main__":
    main()
