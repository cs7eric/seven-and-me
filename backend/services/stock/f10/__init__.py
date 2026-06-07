"""F10 / 题材 / 估值 / 行情聚合的适配器层。

当前只实现 ``EltdxFundamentalsAdapter``，对应通达信 7709 + 7615 数据源。
后续如果接入第二数据源（新浪 / 东财 / tushare），只需新增一个继承
``FundamentalsAdapter`` 的实现类，并在 ``service.py`` 中切换即可。
"""
from .base import FundamentalsAdapter
from .eltdx_adapter import EltdxFundamentalsAdapter
from .index_codes import (
    CONCEPT_INDEX_CODES,
    INDUSTRY_INDEX_CODES,
    all_index_codes,
    get_concept_codes,
    get_industry_codes,
)
from .limit_count import (
    merge_into_breadth,
    read_limit_up_down_cache,
    refresh_limit_up_down,
)
from .schemas import (
    BusinessComposition,
    CompanyProfile,
    FinanceDiagnosis,
    FinanceReport,
    Governance,
    LimitUpDownCount,
    ProfitForecast,
    RankingDetail,
    SectorMarket,
    StockInfo,
    StockScore,
    StockTopic,
    StockTopics,
    StockTopicsCombined,
    ThemeMarket,
    TopicDetail,
    TopicInfo,
    TopicStock,
    TopicStockTable,
    TurnoverRateEntry,
    TurnoverRateSeries,
    Valuation,
)
from .helpers import (
    all_concept_index_codes,
    all_industry_index_codes,
    concept_index_kline,
    industry_index_kline,
    index_kline,
    stock_topics,
    topic_stocks,
)
from .service import (
    FundamentalsService,
    get_fundamentals_service,
    reset_fundamentals_service,
)
from .turnover import refresh_turnover_rate

__all__ = [
    "BusinessComposition",
    "CONCEPT_INDEX_CODES",
    "CompanyProfile",
    "EltdxFundamentalsAdapter",
    "FinanceDiagnosis",
    "FinanceReport",
    "FundamentalsAdapter",
    "FundamentalsService",
    "Governance",
    "INDUSTRY_INDEX_CODES",
    "LimitUpDownCount",
    "ProfitForecast",
    "RankingDetail",
    "SectorMarket",
    "StockInfo",
    "StockScore",
    "StockTopic",
    "StockTopics",
    "StockTopicsCombined",
    "ThemeMarket",
    "TopicDetail",
    "TopicInfo",
    "TopicStock",
    "TopicStockTable",
    "TurnoverRateEntry",
    "TurnoverRateSeries",
    "Valuation",
    "all_index_codes",
    "get_concept_codes",
    "get_fundamentals_service",
    "get_industry_codes",
    "merge_into_breadth",
    "read_limit_up_down_cache",
    "refresh_limit_up_down",
    "refresh_turnover_rate",
    "reset_fundamentals_service",
    "stock_topics",
    "topic_stocks",
    "industry_index_kline",
    "concept_index_kline",
    "all_industry_index_codes",
    "all_concept_index_codes",
    "index_kline",
]
