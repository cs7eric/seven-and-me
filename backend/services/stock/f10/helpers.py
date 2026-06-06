"""eltdx 风格的高阶 Helper。

提供两组函数：

**概念 / 题材 维度（对应 eltdx ``client.helpers``）**
  - :func:`topic_stocks` — 查某个概念 / 题材里的股票（可按名称匹配）
  - :func:`stock_topics` — 查某只股票关联的全部概念 / 题材

**行业 / 概念 指数 维度（直接走 eltdx ``client.bars.get(kind="index")``）**
  - :func:`industry_index_kline` — 拉某个申万行业指数的完整 K 线历史
  - :func:`concept_index_kline` — 拉某个概念主题指数的完整 K 线历史
  - :func:`all_industry_index_codes` — 全量 32 个申万一级行业指数代码
  - :func:`all_concept_index_codes` — 全量 49 个常用概念主题指数代码

底层走 :class:`FundamentalsAdapter`，目前实现是 :class:`EltdxFundamentalsAdapter`，
自动享受 30 分钟 TTL 缓存 + 降级到陈旧缓存的能力。

参考 eltdx 文档：
  - docs/helpers/概念板块成分股.md
  - docs/helpers/个股概念板块.md
  - docs/methods/K线.md（kind="index" 用于指数类品种）
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

from eltdx import TdxClient

from .index_codes import (
    CONCEPT_INDEX_CODES,
    INDUSTRY_INDEX_CODES,
    get_concept_codes,
    get_industry_codes,
)
from .schemas import StockTopic, StockTopics, TopicDetail, TopicStock, TopicStockTable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# K-line period → eltdx 协议层代号
# ---------------------------------------------------------------------------

_PERIOD_ALIASES: dict[str, int | str] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "60m": 60,
    "1h": 60,
    "1d": "day",
    "1w": "week",
    "1M": "month",
}


# ---------------------------------------------------------------------------
# 概念 / 题材 维度
# ---------------------------------------------------------------------------


def topic_stocks(
    seed_code: str,
    *,
    topic_id: str | None = None,
    topic_name: str | None = None,
    sort_by: str = "zdf",
    section: str = "gndbzfsj",
    service=None,
) -> TopicStockTable:
    """查询某个概念 / 题材里的成分股，并整理成表。"""
    from .service import get_fundamentals_service

    svc = service or get_fundamentals_service()

    if not topic_id and not topic_name:
        raise ValueError("topic_id 或 topic_name 至少传一个")

    combined_payload = svc.get_stock_topics(seed_code)
    candidates: list[dict[str, Any]] = combined_payload.get("topics", []) or []

    resolved_topic_id = topic_id or ""
    resolved_topic_name = topic_name or ""

    if resolved_topic_id and not resolved_topic_name:
        match = next(
            (item for item in candidates if str(item.get("topic_id") or "") == resolved_topic_id),
            None,
        )
        if match:
            resolved_topic_name = str(match.get("topic_name") or "")
    elif resolved_topic_name and not resolved_topic_id:
        lowered = resolved_topic_name.strip().lower()
        match = next(
            (
                item for item in candidates
                if (item.get("topic_name") or "").strip().lower() == lowered
            ),
            None,
        ) or next(
            (
                item for item in candidates
                if lowered in (item.get("topic_name") or "").strip().lower()
            ),
            None,
        )
        if not match:
            raise LookupError(
                f"股票 {seed_code} 的关联题材里没有找到名称匹配 '{topic_name}' 的条目"
            )
        resolved_topic_id = str(match.get("topic_id") or "")
        resolved_topic_name = str(match.get("topic_name") or topic_name)

    if not resolved_topic_id:
        raise ValueError("未能解析出 topic_id")

    detail: TopicDetail = svc._adapter.get_topic_compare(
        seed_code, resolved_topic_id, section=section, sort_by=sort_by
    )

    rows: list[TopicStock] = []
    for stock in detail.stocks:
        rows.append(_augment_topic_stock(stock))

    return TopicStockTable(
        seed_code=seed_code,
        topic_id=resolved_topic_id,
        topic_name=resolved_topic_name or detail.topic_name,
        sort_by=sort_by,
        section=section,
        rows=rows,
        count=len(rows),
        source=getattr(svc._adapter, "name", "eltdx"),
    )


def stock_topics(
    code: str,
    *,
    service=None,
) -> StockTopics:
    """查询某只股票关联的全部概念 / 题材。"""
    from .service import get_fundamentals_service

    svc = service or get_fundamentals_service()
    combined_payload = svc.get_stock_topics(code)
    raw_topics = combined_payload.get("topics", []) or []

    topics: list[StockTopic] = []
    for raw in raw_topics:
        topics.append(
            StockTopic(
                topic_id=str(raw.get("topic_id") or ""),
                topic_name=str(raw.get("topic_name") or ""),
                relation_level=raw.get("relation_level"),
                selected_date=raw.get("selected_date"),
                topic_date=raw.get("topic_date"),
                reason=raw.get("reason"),
                detail_id=raw.get("detail_id"),
                category_raw=raw.get("category_raw"),
                source=raw.get("source") or "helpers.stock_topics",
                raw=raw.get("raw"),
            )
        )

    return StockTopics(
        code=code,
        topics=topics,
        count=len(topics),
        source=getattr(svc._adapter, "name", "eltdx"),
    )


# ---------------------------------------------------------------------------
# 行业 / 概念 指数 维度
# ---------------------------------------------------------------------------


def _normalize_period(period: str) -> str:
    """``5m`` / ``60m`` / ``day`` / ``week`` 都能识别。"""
    key = period.strip()
    if key in _PERIOD_ALIASES:
        return str(_PERIOD_ALIASES[key])
    if key in {"day", "week", "month", "5m", "15m", "30m", "60m", "1m", "year"}:
        return key
    raise ValueError(
        f"不支持的 period: {period!r}，可选 {sorted(_PERIOD_ALIASES.keys())}"
    )


def _fetch_index_kline_bars(
    code: str,
    *,
    period: str,
    count: int,
) -> list[dict[str, Any]]:
    """直接走 ``eltdx.TdxClient.bars.get(kind='index')``。

    不走 :class:`FundamentalsAdapter`，因为 adapter 只取 count=2 算当日涨跌幅；
    这里要拿完整 K 线历史。
    """
    if count <= 0 or count > 2000:
        raise ValueError("count 必须在 1-2000 之间")
    normalized = _normalize_period(period)
    with TdxClient(timeout=5) as client:
        page = client.bars.get(
            code,
            period=normalized,
            count=count,
            kind="index",
        )
    bars = getattr(page, "bars", None) or []
    out: list[dict[str, Any]] = []
    for bar in bars:
        # eltdx 的 bar 有: time / open / high / low / close / volume_lots / amount /
        # last_close_price_milli (前收)。把毫厘价 → 元
        prev_close_milli = getattr(bar, "last_close_price_milli", None)
        prev_close = (prev_close_milli / 1000.0) if prev_close_milli else None
        pct = None
        if prev_close and prev_close != 0:
            pct = (bar.close / prev_close - 1.0) * 100.0
        out.append(
            {
                "time": str(getattr(bar, "time", "")),
                "open": float(getattr(bar, "open", 0.0)),
                "high": float(getattr(bar, "high", 0.0)),
                "low": float(getattr(bar, "low", 0.0)),
                "close": float(getattr(bar, "close", 0.0)),
                "prev_close": prev_close,
                "pct": pct,
                "volume_lots": int(getattr(bar, "volume_lots", 0) or 0),
                "amount": float(getattr(bar, "amount", 0.0) or 0.0),
            }
        )
    return out


def industry_index_kline(
    code: str,
    *,
    period: str = "day",
    count: int = 120,
) -> dict[str, Any]:
    """拉取某个**申万行业指数**的完整 K 线。

    ``code`` 必须是 ``sh8803XX`` 格式 (来自 :data:`INDUSTRY_INDEX_CODES`)。
    ``period`` 支持 ``1m/5m/15m/30m/60m/1d/1w/1M``。

    返回结构::

        {
            "code": "sh880301",
            "name": "农副食品",
            "kind": "industry",
            "period": "day",
            "count": 120,
            "bars": [
                {"time": "2026-06-03 15:00:00", "open": ..., "high": ...,
                 "low": ..., "close": ..., "prev_close": ..., "pct": ...,
                 "volume_lots": ..., "amount": ...},
                ...
            ],
            "source": "eltdx",
        }
    """
    name = _lookup_index_name(code, INDUSTRY_INDEX_CODES)
    bars = _fetch_index_kline_bars(code, period=period, count=count)
    return {
        "code": code,
        "name": name or "",
        "kind": "industry",
        "period": _normalize_period(period),
        "count": len(bars),
        "bars": bars,
        "source": "eltdx",
    }


def concept_index_kline(
    code: str,
    *,
    period: str = "day",
    count: int = 120,
) -> dict[str, Any]:
    """拉取某个**概念主题指数**的完整 K 线。

    ``code`` 必须是 ``sh8804XX`` 格式 (来自 :data:`CONCEPT_INDEX_CODES`)。
    """
    name = _lookup_index_name(code, CONCEPT_INDEX_CODES)
    bars = _fetch_index_kline_bars(code, period=period, count=count)
    return {
        "code": code,
        "name": name or "",
        "kind": "concept",
        "period": _normalize_period(period),
        "count": len(bars),
        "bars": bars,
        "source": "eltdx",
    }


def all_industry_index_codes() -> list[dict[str, str]]:
    """全量 32 个申万一级行业指数代码。"""
    return [{"code": c, "name": n, "kind": "industry"} for c, n in INDUSTRY_INDEX_CODES]


def all_concept_index_codes() -> list[dict[str, str]]:
    """全量 49 个常用概念主题指数代码。"""
    return [{"code": c, "name": n, "kind": "concept"} for c, n in CONCEPT_INDEX_CODES]


def _lookup_index_name(code: str, table: Iterable[tuple[str, str]]) -> str | None:
    code_lower = code.strip().lower()
    for c, n in table:
        if c.lower() == code_lower:
            return n
    return None


# ---------------------------------------------------------------------------
# 工具方法
# ---------------------------------------------------------------------------


def _augment_topic_stock(stock: TopicStock) -> TopicStock:
    """从 ``full_code`` 拆出 ``exchange / market_id / code``，便于前端直接用。"""
    full = (stock.full_code or "").strip().lower()
    if not full:
        return stock
    if full.startswith(("sh", "sz", "bj")) and len(full) >= 2:
        exchange = full[:2]
        market_id = full[2:3] if len(full) >= 3 else ""
        code = full[3:] if len(full) >= 4 else full[2:]
    else:
        exchange = ""
        market_id = ""
        code = full
    return TopicStock(
        full_code=stock.full_code,
        name=stock.name,
        exchange=exchange or None,
        market_id=market_id or None,
        code=code or None,
        rank=stock.rank,
        change_pct=stock.change_pct,
        change_pct_3d=stock.change_pct_3d,
        change_pct_5d=stock.change_pct_5d,
        change_pct_20d=stock.change_pct_20d,
        change_pct_60d=stock.change_pct_60d,
        change_pct_ytd=stock.change_pct_ytd,
        trading_date=stock.trading_date,
        raw=stock.raw if getattr(stock, "raw", None) else None,
    )


__all__ = [
    "all_concept_index_codes",
    "all_industry_index_codes",
    "concept_index_kline",
    "industry_index_kline",
    "stock_topics",
    "topic_stocks",
]

