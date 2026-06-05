"""统一数据结构（F10 / 题材 / 估值 / 涨停跌停 / 换手率）。

所有返回给路由层 / 前端的 dataclass 都以 ``to_dict()`` 提供可序列化字典。
新数据源接入时**不应**修改这里，只能在适配器内做翻译。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if v is not None}


# ---------------------------------------------------------------------------
# 概念 / 题材
# ---------------------------------------------------------------------------


@dataclass
class TopicInfo:
    """个股关联题材的最小信息单元。"""

    topic_id: str
    topic_name: str
    relation_level: int | None = None
    selected_date: str | None = None
    topic_date: str | None = None
    reason: str | None = None
    detail_id: str | None = None
    category_raw: str | None = None
    source: str | None = None
    raw: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return _strip_none(asdict(self))


@dataclass
class StockTopicsCombined:
    """个股关联题材（合并 topic_ids + hot_topics，带可读 topic_name）。

    推荐使用 :func:`EltdxFundamentalsAdapter.get_stock_topics_combined` 取得。
    """

    symbol: str
    topics: list[TopicInfo] = field(default_factory=list)
    count: int = 0
    source: str = "eltdx"
    fetched_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "topics": [item.to_dict() for item in self.topics],
            "count": self.count,
            "source": self.source,
            "fetched_at": self.fetched_at,
        }


@dataclass
class SectorMarket:
    """板块行情列表（行业 / 概念板块）。

    返回字段对齐 :class:`CategoryQuoteRecord`，最常用的几个：
    ``full_code / name / last_price / change_pct / amount / total_hand / open_amount /
    open_pct / high_pct / low_pct / amplitude_pct / locked_amount / entrust_ratio``。
    """

    category: str
    sort_by: str
    ascending: bool
    total: int
    items: list[dict[str, Any]] = field(default_factory=list)
    source: str = "eltdx"
    fetched_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "sort_by": self.sort_by,
            "ascending": self.ascending,
            "total": self.total,
            "items": self.items,
            "source": self.source,
            "fetched_at": self.fetched_at,
        }


@dataclass
class TopicStock:
    """题材内成分股单元（含涨跌幅）。"""

    full_code: str
    name: str
    exchange: str | None = None
    market_id: str | None = None
    code: str | None = None
    rank: int | None = None
    change_pct: float | None = None
    change_pct_3d: float | None = None
    change_pct_5d: float | None = None
    change_pct_20d: float | None = None
    change_pct_60d: float | None = None
    change_pct_ytd: float | None = None
    trading_date: str | None = None
    raw: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return _strip_none(asdict(self))


@dataclass
class TopicDetail:
    """题材详情：题材本身 + 成分股列表。"""

    topic_id: str
    topic_name: str
    seed_code: str
    stocks: list[TopicStock] = field(default_factory=list)
    raw: dict[str, Any] | None = None
    fetched_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "topic_name": self.topic_name,
            "seed_code": self.seed_code,
            "stocks": [item.to_dict() for item in self.stocks],
            "raw": self.raw,
            "fetched_at": self.fetched_at,
        }


# ---------------------------------------------------------------------------
# eltdx 风格 Helper 返回模型
# ---------------------------------------------------------------------------


@dataclass
class TopicStockTable:
    """题材内成分股表（按服务端排名字段整理）。

    对应 eltdx ``client.helpers.topic_stocks(...)`` 的返回模型。
    """

    seed_code: str
    topic_id: str
    topic_name: str
    sort_by: str
    section: str
    rows: list[TopicStock] = field(default_factory=list)
    count: int = 0
    source: str = "eltdx"
    fetched_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed_code": self.seed_code,
            "topic_id": self.topic_id,
            "topic_name": self.topic_name,
            "sort_by": self.sort_by,
            "section": self.section,
            "rows": [item.to_dict() for item in self.rows],
            "count": self.count,
            "source": self.source,
            "fetched_at": self.fetched_at,
        }


@dataclass
class StockTopic:
    """个股关联题材（elper 风格，category_raw / source / raw 完整保留）。"""

    topic_id: str
    topic_name: str
    relation_level: int | None = None
    selected_date: str | None = None
    topic_date: str | None = None
    reason: str | None = None
    detail_id: str | None = None
    category_raw: str | None = None
    source: str | None = None
    raw: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return _strip_none(asdict(self))


@dataclass
class StockTopics:
    """个股关联题材集合（eltdx helpers.stock_topics 返回模型）。"""

    code: str
    topics: list[StockTopic] = field(default_factory=list)
    count: int = 0
    source: str = "eltdx"
    fetched_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "topics": [item.to_dict() for item in self.topics],
            "count": self.count,
            "source": self.source,
            "fetched_at": self.fetched_at,
        }


# ---------------------------------------------------------------------------
# 涨停跌停数量
# ---------------------------------------------------------------------------


@dataclass
class LimitUpDownCount:
    """全市场涨停 / 跌停数量统计。"""

    trade_date: str
    up_count: int
    down_count: int
    flat_count: int
    limit_up_count: int
    limit_down_count: int
    total_count: int
    threshold_rules: dict[str, float] = field(
        default_factory=lambda: {
            "main_board": 9.95,
            "chinext_star": 19.95,
            "bse": 29.95,
            "st": 4.95,
        }
    )
    source: str = "eltdx"
    fetched_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# 换手率
# ---------------------------------------------------------------------------


@dataclass
class TurnoverRateEntry:
    """单日 K 线的换手率补充。"""

    trade_date: str | None = None
    timestamp: int = 0
    turnover_rate: float = 0.0
    volume: float = 0.0
    amount: float = 0.0
    circulating_shares: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TurnoverRateSeries:
    """个股换手率序列。"""

    symbol: str
    target_type: str
    period: str
    adjust: str
    circulating_shares: float | None
    total_shares: float | None
    source: str = "eltdx"
    entries: list[TurnoverRateEntry] = field(default_factory=list)
    updated_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "target_type": self.target_type,
            "period": self.period,
            "adjust": self.adjust,
            "circulating_shares": self.circulating_shares,
            "total_shares": self.total_shares,
            "source": self.source,
            "entries": [item.to_dict() for item in self.entries],
            "updated_at": self.updated_at,
        }


# ---------------------------------------------------------------------------
# F10 基础 / 公司概况
# ---------------------------------------------------------------------------


@dataclass
class StockInfo:
    """个股基础信息（用于页面初始化）。"""

    symbol: str
    raw: dict[str, Any] = field(default_factory=dict)
    fetched_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "raw": self.raw,
            "fetched_at": self.fetched_at,
        }


@dataclass
class CompanyProfile:
    """公司概况（发行 / 上市信息等）。"""

    symbol: str
    section: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] | None = None
    fetched_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "section": self.section,
            "rows": self.rows,
            "raw": self.raw,
            "fetched_at": self.fetched_at,
        }


@dataclass
class BusinessComposition:
    """主营构成。"""

    symbol: str
    report_date: str | None
    rows: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] | None = None
    fetched_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "report_date": self.report_date,
            "rows": self.rows,
            "raw": self.raw,
            "fetched_at": self.fetched_at,
        }


# ---------------------------------------------------------------------------
# 估值 / 财务
# ---------------------------------------------------------------------------


@dataclass
class Valuation:
    """估值表（PE / PB / PS / PCF / 估值百分位 / 市值）。"""

    symbol: str
    req_id: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] | None = None
    fetched_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "req_id": self.req_id,
            "rows": self.rows,
            "raw": self.raw,
            "fetched_at": self.fetched_at,
        }


@dataclass
class FinanceReport:
    """财务报表（资产负债 / 利润 / 现金流）。"""

    symbol: str
    report_type: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] | None = None
    fetched_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "report_type": self.report_type,
            "rows": self.rows,
            "raw": self.raw,
            "fetched_at": self.fetched_at,
        }


@dataclass
class FinanceDiagnosis:
    """财务诊断（运营 / 盈利 / 成长 / 现金流 / 资产质量）。"""

    symbol: str
    section: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] | None = None
    fetched_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "section": self.section,
            "rows": self.rows,
            "raw": self.raw,
            "fetched_at": self.fetched_at,
        }


@dataclass
class StockScore:
    """个股总评 / 资金面 / 基本面 / 主题面评分。"""

    symbol: str
    section: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] | None = None
    fetched_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "section": self.section,
            "rows": self.rows,
            "raw": self.raw,
            "fetched_at": self.fetched_at,
        }


@dataclass
class ProfitForecast:
    """业绩预测 / 评级。"""

    symbol: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] | None = None
    fetched_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "rows": self.rows,
            "raw": self.raw,
            "fetched_at": self.fetched_at,
        }


# ---------------------------------------------------------------------------
# 排名 / 治理 / 题材行情
# ---------------------------------------------------------------------------


@dataclass
class RankingDetail:
    """市场 / 行业排名明细。"""

    symbol: str
    section: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] | None = None
    fetched_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "section": self.section,
            "rows": self.rows,
            "raw": self.raw,
            "fetched_at": self.fetched_at,
        }


@dataclass
class Governance:
    """资本运作 / 治理（违规 / 担保 / 高管）。"""

    symbol: str
    section: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] | None = None
    fetched_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "section": self.section,
            "rows": self.rows,
            "raw": self.raw,
            "fetched_at": self.fetched_at,
        }


# ---------------------------------------------------------------------------
# 题材行情（theme_market 复合响应）
# ---------------------------------------------------------------------------


@dataclass
class ThemeMarket:
    """题材概念行情（HQServ.hq_nlp_tcihq 复合响应）。

    raw 字段保留原始表，rows 是适配器从多张表里挑出的"相关板块"通用结构。
    """

    symbol: str
    req_id: str
    sections: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    raw: dict[str, Any] | None = None
    fetched_at: str = field(default_factory=_utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "req_id": self.req_id,
            "sections": self.sections,
            "raw": self.raw,
            "fetched_at": self.fetched_at,
        }
