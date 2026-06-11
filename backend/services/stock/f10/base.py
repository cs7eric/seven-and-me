"""适配器抽象接口。

所有 F10 / 题材 / 涨停跌停 / 换手率相关的数据源都应实现该接口。
当前唯一实现见 :mod:`eltdx_adapter`。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .schemas import (
    Announcements,
    BusinessComposition,
    CompanyNews,
    CompanyProfile,
    FinanceDiagnosis,
    FinanceReport,
    Governance,
    LimitUpDownCount,
    NewsList,
    ProfitForecast,
    RankingDetail,
    Roadshows,
    SectorMarket,
    StockInfo,
    StockScore,
    StockTopicsCombined,
    ThemeMarket,
    TopicDetail,
    TopicInfo,
    TurnoverRateSeries,
    Valuation,
)


class FundamentalsAdapter(ABC):
    """F10 / 题材 / 行情数据源适配器抽象基类。

    命名约定：
    - 同步方法：返回 dataclass（to_dict 可序列化）
    - 复合方法：返回带 raw 字段的 dataclass，方便上游做兜底解析
    - 错误约定：底层异常向上抛，由 service 层做降级
    """

    # -------- 题材 / 概念 --------

    @abstractmethod
    def get_topic_ids(self, symbol: str) -> list[str]:
        """获取个股关联题材 ID 列表。"""

    @abstractmethod
    def get_hot_topics(self, symbol: str, section: str = "zttzbkz") -> list[TopicInfo]:
        """热点题材（含板块 / 主题 / 关联度等）。"""

    @abstractmethod
    def get_topic_compare(
        self, symbol: str, topic_id: str, section: str = "gndbzfsj", sort_by: str = "zdf"
    ) -> TopicDetail:
        """题材内个股对比 / 排名。"""

    @abstractmethod
    def get_stock_topics_combined(self, symbol: str) -> StockTopicsCombined:
        """个股关联题材（合并 topic_ids + hot_topics，带可读 topic_name）。

        推荐主路径。eltdx 的 helpers 已自动合并。
        """

    @abstractmethod
    def list_sectors_market(
        self,
        category: str,
        sort_by: str = "涨幅",
        count: int = 100,
        ascending: bool = False,
    ) -> SectorMarket:
        """按分类拉板块 / 个股行情（涨幅、成交额、量等）。"""

    @abstractmethod
    def get_industry_sectors_market(
        self,
        sort_by: str = "涨幅",
        count: int = 100,
        ascending: bool = False,
        start: int = 0,
    ) -> SectorMarket:
        """拉取所有行业指数（申万 32 个行业）的当日行情。

        实现原理：遍历 ``index_codes.INDUSTRY_INDEX_CODES``，对每个行业指数代码
        调 ``client.bars.get(code, period="1d", count=2)`` 拿最近 2 个交易日的
        K 线，再派生 ``change_pct / open_pct / high_pct / low_pct / amplitude_pct``。
        """

    @abstractmethod
    def get_concept_sectors_market(
        self,
        sort_by: str = "涨幅",
        count: int = 100,
        ascending: bool = False,
        start: int = 0,
    ) -> SectorMarket:
        """拉取所有概念主题指数（~50 个常用概念）的当日行情。

        同上，遍历 ``index_codes.CONCEPT_INDEX_CODES`` 走 K 线接口。
        """

    @abstractmethod
    def get_theme_market(self, symbol: str, req_id: str = "200743") -> ThemeMarket:
        """题材概念行情（HQServ.hq_nlp_tcihq 复合响应）。"""

    # -------- 涨停跌停 / 换手率 --------

    @abstractmethod
    def count_limit_up_down(
        self,
        *,
        category: str = "沪深A股",
        max_pages: int = 80,
    ) -> LimitUpDownCount:
        """按涨跌幅 + 板块阈值统计全市场涨停 / 跌停 / 上涨 / 下跌家数。"""

    @abstractmethod
    def compute_turnover_rate_series(
        self,
        symbol: str,
        target_type: str,
        period: str = "1d",
        adjust: str = "qfq",
    ) -> TurnoverRateSeries:
        """结合 K 线与流通股本，计算单股换手率序列。"""

    # -------- F10 基础 --------

    @abstractmethod
    def get_stock_info(self, symbol: str) -> StockInfo: ...

    @abstractmethod
    def get_company_profile(self, symbol: str, section: str = "8") -> CompanyProfile: ...

    @abstractmethod
    def get_business_composition(
        self, symbol: str, report_date: str | None = None
    ) -> BusinessComposition: ...

    # -------- F10 财务 / 估值 --------

    @abstractmethod
    def get_valuation(self, symbol: str, req_id: str = "200191") -> Valuation: ...

    @abstractmethod
    def get_finance_report(self, symbol: str, report_type: str = "zcfzb") -> FinanceReport: ...

    @abstractmethod
    def get_finance_diagnosis(self, symbol: str, section: str = "yynl") -> FinanceDiagnosis: ...

    @abstractmethod
    def get_stock_score(self, symbol: str, section: str = "pf") -> StockScore: ...

    @abstractmethod
    def get_profit_forecast(self, symbol: str) -> ProfitForecast: ...

    # -------- F10 排名 / 治理 --------

    @abstractmethod
    def get_ranking_detail(self, symbol: str, section: str = "scpmdela") -> RankingDetail: ...

    @abstractmethod
    def get_governance(self, symbol: str, section: str = "wgcl") -> Governance: ...

    # -------- 公告 / 新闻 / 路演 / 研报 (eltdx 1.0+) --------

    @abstractmethod
    def get_announcements(self, symbol: str) -> Announcements: ...

    @abstractmethod
    def get_news(self, symbol: str) -> NewsList: ...

    @abstractmethod
    def get_roadshows(self, symbol: str) -> Roadshows: ...

    @abstractmethod
    def get_company_news(self, symbol: str, section: str = "gsyj") -> CompanyNews: ...

    # -------- 健康检查 --------

    @abstractmethod
    def ping(self) -> dict[str, Any]:
        """健康检查：返回数据源名 / 是否可用 / 延迟等。"""
