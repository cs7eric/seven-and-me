"""Market Overview PG write helper — 供 service 层在落盘 JSON 后同步写 PG.

维护前请先看:
`F:\dev-repo\mp4-to-word-new\design\backend\market-overview-json-to-postgres.md`
"""
from __future__ import annotations

import logging
from typing import Any

from backend.config.database import session_scope
from backend.repositories.market.market_overview_pg_repo import MarketOverviewPgRepository

logger = logging.getLogger(__name__)

# JSON camelCase → PG snake_case field mapping
_FIELD_MAP = {
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


def upsert_overview_to_pg(
    payload: dict[str, Any],
    source_tag: str = "akshare",
) -> None:
    """将 JSON payload 中的字段同步写入 PG (非致命, 失败不影响主流程)."""
    try:
        # Convert camelCase JSON fields to snake_case PG fields
        fields = {}
        trading_date = payload.get("tradingDate")
        for camel, snake in _FIELD_MAP.items():
            v = payload.get(camel)
            if v is not None:
                fields[snake] = v

        if not trading_date or not fields:
            logger.debug("upsert_overview_to_pg skipped: no data for %s", trading_date)
            return

        with session_scope() as db:
            repo = MarketOverviewPgRepository(db)
            repo.upsert(trade_date=trading_date, fields=fields, source_tag=source_tag)

        logger.debug("market_overview_pg: upserted %s (source=%s)", trading_date, source_tag)
    except Exception as exc:
        logger.warning("upsert_overview_to_pg failed (non-fatal): %s", exc)
