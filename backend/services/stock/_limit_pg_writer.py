"""Limit Emotion PG write helper — 供 service 层在落盘 JSON 后同步写 PG.

维护前请先看:
`F:\dev-repo\mp4-to-word-new\design\backend\limit-emotion-json-to-postgres.md`
"""
from __future__ import annotations

import logging
from typing import Any

from backend.config.database import session_scope
from backend.repositories.market.market_limit_pg_repo import MarketLimitPgRepository

logger = logging.getLogger(__name__)


def _extract_stocks_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """从 computed payload 提取逐股明细 (涨停/跌停/炸板).

    涨停股票的板数从 ``streak.distribution[].streak`` 获取 (分布桶级别),
    跌停股票板数为 0, 炸板股票板数为 ``previousStreak``.
    """
    stocks: list[dict[str, Any]] = []
    streak_data = payload.get("streak") or {}

    # 1) 涨停股: 遍历 distribution 桶, 桶级别有 streak 字段
    distribution = streak_data.get("distribution") or []
    for bucket in distribution:
        bucket_streak = bucket.get("streak")
        for s in (bucket.get("stocks") or []):
            stocks.append({
                "code": s.get("code"),
                "name": s.get("name"),
                "category": "limit_up",
                "streak": bucket_streak,
                "changePct": s.get("changePct"),
                "limitUpPrice": s.get("limitUpPrice"),
            })

    # 2) 跌停股
    limit_down = payload.get("limitDown") or {}
    for s in (limit_down.get("stocks") or []):
        stocks.append({
            "code": s.get("code"),
            "name": s.get("name"),
            "category": "limit_down",
            "streak": 0,
            "changePct": s.get("changePct"),
            "limitDownPrice": s.get("limitDownPrice"),
        })

    # 3) 炸板股
    broken = streak_data.get("broken") or {}
    for s in (broken.get("stocks") or []):
        stocks.append({
            "code": s.get("code"),
            "name": s.get("name"),
            "category": "broken",
            "streak": s.get("previousStreak"),
            "changePct": s.get("changePct"),
        })

    return stocks


def upsert_limit_snapshot_to_pg(
    payload: dict[str, Any],
    source_tag: str = "realtime",
) -> None:
    """将 computed limitEmotion payload 中的摘要字段同步写入 PG.

    Args:
        payload: ``build_limit_emotion()`` 的返回值 (包含 limitUp/limitDown/breakBoard/streak).
        source_tag: 数据来源标记.
    """
    try:
        trading_date = payload.get("tradeDate")
        if not trading_date:
            logger.debug("upsert_limit_snapshot_to_pg skipped: no tradeDate")
            return

        # 从嵌套 payload 提取摘要字段
        limit_up = payload.get("limitUp") or {}
        limit_down = payload.get("limitDown") or {}
        break_board = payload.get("breakBoard") or {}
        streak = payload.get("streak") or {}
        meta = payload.get("_meta") or {}

        fields: dict[str, Any] = {
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
            "source": source_tag,
        }
        # 过滤 None, 只传有值的字段
        clean_fields = {k: v for k, v in fields.items() if v is not None}

        if not clean_fields:
            logger.debug("upsert_limit_snapshot_to_pg skipped: no fields for %s", trading_date)
            return

        # 从 payload 提取股票明细
        stock_rows = _extract_stocks_from_payload(payload)

        with session_scope() as db:
            repo = MarketLimitPgRepository(db)
            repo.upsert(
                trade_date=trading_date,
                fields=clean_fields,
                source_tag=source_tag,
                extra_payload=payload,
            )
            if stock_rows:
                repo.upsert_stocks(trade_date=trading_date, stocks=stock_rows)

        logger.debug("market_limit_pg: upserted %s (source=%s, %d stocks)",
                     trading_date, source_tag, len(stock_rows))
    except Exception as exc:
        logger.warning("upsert_limit_snapshot_to_pg failed (non-fatal): %s", exc)
