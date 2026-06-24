r"""手动粘贴的资金流数据 (主力净流入 / 4 单 净流入 + 净比).

维护前请先看:
`F:\dev-repo\mp4-to-word-new\design\backend\market-overview-json-to-postgres.md`

运行时真源已经收口到 PostgreSQL: manual save / load 都直接读写
`app.market_overview_snapshots`, 不再依赖 JSON manual/archive 持久化.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from backend.config.database import session_scope
from backend.repositories.market.market_overview_pg_repo import MarketOverviewPgRepository

logger = logging.getLogger(__name__)

# manual 只允许维护这 10 个资金流字段
_MANUAL_MERGE_FIELDS = (
    "mainNetInflow", "mainNetInflowRatio",
    "superLargeNetInflow", "superLargeNetInflowRatio",
    "largeNetInflow", "largeNetInflowRatio",
    "mediumNetInflow", "mediumNetInflowRatio",
    "smallNetInflow", "smallNetInflowRatio",
)


def save_manual_fund_flow(trading_date: str, fields: dict[str, Any]) -> dict[str, Any]:
    """保存手动粘贴的资金流数据到 PostgreSQL."""
    allowed = set(_MANUAL_MERGE_FIELDS)
    cleaned: dict[str, Any] = {}
    for k, v in fields.items():
        if k in allowed and v is not None:
            try:
                cleaned[k] = float(v)
            except (TypeError, ValueError):
                continue

    payload: dict[str, Any] = {
        "tradingDate": trading_date,
        "savedAt": datetime.now().isoformat(timespec="seconds"),
        "source": "manual",
        **cleaned,
    }
    for k in allowed:
        payload.setdefault(k, None)

    from backend.services.stock._pg_writer import upsert_overview_to_pg

    manual_payload = {
        "tradingDate": trading_date,
        **cleaned,
    }
    upsert_overview_to_pg(manual_payload, source_tag="manual")
    logger.info("manual fund flow saved to pg: %s (fields=%d)", trading_date, len(cleaned))
    return payload


def load_manual_fund_flow(trading_date: str) -> dict[str, Any] | None:
    """从 PostgreSQL 读取指定交易日的 manual 资金流数据."""
    with session_scope() as db:
        repo = MarketOverviewPgRepository(db)
        row = repo.get_manual(trading_date)

    if not row:
        return None

    payload = {
        "tradingDate": row.get("trade_date") or trading_date,
        "savedAt": row.get("manual_updated_at") or row.get("updated_at") or row.get("created_at"),
        "source": "manual",
        "mainNetInflow": row.get("main_net_inflow"),
        "mainNetInflowRatio": row.get("main_net_inflow_ratio"),
        "superLargeNetInflow": row.get("super_large_net_inflow"),
        "superLargeNetInflowRatio": row.get("super_large_net_ratio"),
        "largeNetInflow": row.get("large_net_inflow"),
        "largeNetInflowRatio": row.get("large_net_ratio"),
        "mediumNetInflow": row.get("medium_net_inflow"),
        "mediumNetInflowRatio": row.get("medium_net_ratio"),
        "smallNetInflow": row.get("small_net_inflow"),
        "smallNetInflowRatio": row.get("small_net_ratio"),
    }
    has_any_value = any(
        payload.get(k) is not None
        for k in (
            "mainNetInflow", "superLargeNetInflow", "largeNetInflow",
            "mediumNetInflow", "smallNetInflow",
        )
    )
    return payload if has_any_value else None
