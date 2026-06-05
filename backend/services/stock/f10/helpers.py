"""eltdx 风格的高阶 Helper。

提供两个 Python 函数，对应 eltdx 客户端 ``client.helpers`` 下的同名方法：

- :func:`topic_stocks` — 查某个概念 / 题材里的股票（可按名称匹配）
- :func:`stock_topics` — 查某只股票关联的全部概念 / 题材

底层走 :class:`FundamentalsAdapter`，目前实现是 :class:`EltdxFundamentalsAdapter`，
自动享受 30 分钟 TTL 缓存 + 降级到陈旧缓存的能力。

参考 eltdx 文档：
  - docs/helpers/概念板块成分股.md
  - docs/helpers/个股概念板块.md
"""
from __future__ import annotations

from typing import Any

from .schemas import StockTopic, StockTopics, TopicDetail, TopicStock, TopicStockTable
from .service import FundamentalsService, get_fundamentals_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def topic_stocks(
    seed_code: str,
    *,
    topic_id: str | None = None,
    topic_name: str | None = None,
    sort_by: str = "zdf",
    section: str = "gndbzfsj",
    service: FundamentalsService | None = None,
) -> TopicStockTable:
    """查询某个概念 / 题材里的成分股，并整理成表。

    Parameters
    ----------
    seed_code:
        种子股票。题材对比接口需要传一只股票 code 配合 topic_id 使用。
    topic_id:
        题材 ID。优先级高于 ``topic_name``。
    topic_name:
        题材名称；当 ``topic_id`` 不传时，会先在 ``seed_code`` 关联的题材里
        按名称匹配（精确 / 子串都支持）。
    sort_by:
        排序字段，对应 eltdx 的 ``sort_by``。常用：

        - ``zdf``    涨跌幅
        - ``zdf_3d`` 近 3 日涨跌幅
        - ``zdf_5d`` 近 5 日
        - ``zdf_20d`` 近 20 日
        - ``zdf_60d`` 近 60 日
        - ``zdf_ys`` 年初至今
    section:
        F10 对比分区，默认 ``gndbzfsj``。
    service:
        注入的 :class:`FundamentalsService` 单例。默认走 :func:`get_fundamentals_service`。
    """
    svc = service or get_fundamentals_service()

    if not topic_id and not topic_name:
        raise ValueError("topic_id 或 topic_name 至少传一个")

    # 在 seed_code 关联的题材里同时找：正向（按 id 找 name）和反向（按 name 找 id）
    combined_payload = svc.get_stock_topics(seed_code)
    candidates: list[dict[str, Any]] = combined_payload.get("topics", []) or []

    resolved_topic_id = topic_id or ""
    resolved_topic_name = topic_name or ""

    if resolved_topic_id and not resolved_topic_name:
        # 反向：用 topic_id 查 name
        match = next(
            (item for item in candidates if str(item.get("topic_id") or "") == resolved_topic_id),
            None,
        )
        if match:
            resolved_topic_name = str(match.get("topic_name") or "")
    elif resolved_topic_name and not resolved_topic_id:
        # 正向：用 name 查 id（先精确后子串）
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
    service: FundamentalsService | None = None,
) -> StockTopics:
    """查询某只股票关联的全部概念 / 题材。

    返回 :class:`StockTopics`，字段与 eltdx ``client.helpers.stock_topics`` 一致。
    """
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
# 工具方法
# ---------------------------------------------------------------------------


def _augment_topic_stock(stock: TopicStock) -> TopicStock:
    """从 ``full_code`` 拆出 ``exchange / market_id / code``，便于前端直接用。

    ``full_code`` 形如 ``sz300975`` / ``sh600519`` / ``bj920971``，长度不固定：

    - 前 2 位是 exchange（sh / sz / bj）
    - 中间 1 位是 market_id（数字 / 字母，eltdx 用 'h' / 'z' / 'b' 等表示沪 / 深 / 北）
    - 剩余位是 code
    """
    full = (stock.full_code or "").strip().lower()
    if not full:
        return stock
    if full.startswith(("sh", "sz", "bj")) and len(full) >= 2:
        exchange = full[:2]
        market_id = full[2:3] if len(full) >= 3 else ""
        code = full[3:] if len(full) >= 4 else full[2:]
    else:
        # 退路：拆不出来就保留 full_code
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


__all__ = ["topic_stocks", "stock_topics"]
