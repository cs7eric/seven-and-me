"""F10 服务层（单例 + 缓存 + 降级）。

- 单例 ``FundamentalsService``：整个进程内复用同一份适配器实例，避免重复连接。
- 缓存：参考 ``market_overview_service``，默认走 `reference/stock/cache/f10/`
  目录，按 symbol + endpoint 维度做 TTL 缓存。
- 降级：适配器抛错时返回上次缓存；都没有则向外抛 ``RuntimeError``。
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from threading import RLock
from typing import Any, Callable

from backend.config.settings import STOCK_REFERENCE_CACHE_FOLDER
from backend.utils.json_io import read_json_file, write_json_file

from .base import FundamentalsAdapter
from .eltdx_adapter import EltdxFundamentalsAdapter, _normalize_category_id
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
    StockTopicsCombined,
    ThemeMarket,
    TopicDetail,
    TopicInfo,
    TurnoverRateSeries,
    Valuation,
)


CACHE_ROOT = STOCK_REFERENCE_CACHE_FOLDER / 'f10'
DEFAULT_TTL_SECONDS = 60 * 30  # 30 分钟


#: 业务侧"行业指数"别名集合（用于 list_sectors_market 的统一分发）。
_INDUSTRY_ALIASES: frozenset[str] = frozenset({
    "行业指数", "行业", "industry", "Industry", "INDUSTRY",
    "sw_industry", "申万行业", "申万一级",
})

#: 业务侧"概念指数"别名集合。
_CONCEPT_ALIASES: frozenset[str] = frozenset({
    "概念指数", "概念", "concept", "Concept", "CONCEPT",
    "concept_topic", "tdx_concept", "通达信概念",
})


class FundamentalsService:
    """F10 适配器服务（单例）。"""

    def __init__(self, adapter: FundamentalsAdapter | None = None, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._adapter = adapter or EltdxFundamentalsAdapter()
        self._ttl_seconds = ttl_seconds
        self._lock = RLock()

    @property
    def adapter(self) -> FundamentalsAdapter:
        return self._adapter

    @property
    def source_name(self) -> str:
        return getattr(self._adapter, "name", "unknown")

    # -------- 通用缓存包装 --------

    def _cache_path(self, scope: str, key: str) -> Path:
        safe = key.replace('/', '_').replace('\\', '_').strip('_') or 'default'
        return CACHE_ROOT / scope / f'{safe}.json'

    def _read_cache(self, scope: str, key: str) -> dict[str, Any] | None:
        path = self._cache_path(scope, key)
        if not path.exists():
            return None
        try:
            with path.open('r', encoding='utf-8') as file:
                payload = json.load(file)
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        if self._ttl_seconds > 0:
            cached_at = float(payload.get('cached_at') or 0)
            if cached_at and (time.time() - cached_at) > self._ttl_seconds:
                return None
        return payload

    def _write_cache(self, scope: str, key: str, payload: dict[str, Any]) -> None:
        path = self._cache_path(scope, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload['cached_at'] = time.time()
        try:
            with path.open('w', encoding='utf-8') as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _execute_with_cache(
        self,
        scope: str,
        key: str,
        producer: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        with self._lock:
            cached = self._read_cache(scope, key)
            if cached is not None:
                cached['cache'] = 'hit'
                return cached
            try:
                data = producer()
            except Exception as exc:
                fallback = self._read_cache(scope, key)
                if fallback is not None:
                    fallback['cache'] = 'stale'
                    fallback['error'] = str(exc)
                    return fallback
                raise RuntimeError(f'F10 {scope} {key} failed: {exc}') from exc
            data['source'] = data.get('source') or self.source_name
            self._write_cache(scope, key, data)
            data['cache'] = 'miss'
            return data

    # -------- 业务方法 --------

    def get_topic_compare(
        self,
        symbol: str,
        topic_id: str,
        section: str = "gndbzfsj",
        sort_by: str = "zdf",
    ) -> dict[str, Any]:
        def _produce() -> dict[str, Any]:
            payload: TopicDetail = self._adapter.get_topic_compare(
                symbol, topic_id, section=section, sort_by=sort_by
            )
            return payload.to_dict()
        return self._execute_with_cache(
            'topic_compare', f'{symbol}-{topic_id}-{section}-{sort_by}', _produce
        )

    def get_stock_topics(self, symbol: str) -> dict[str, Any]:
        """个股关联题材（合并 topic_ids + hot_topics，带可读 topic_name）。

        数据源内部走 ``helpers.stock_topics``，字段映射与 ``F10-热点题材.md`` 一致。
        """
        def _produce() -> dict[str, Any]:
            combined: StockTopicsCombined = self._adapter.get_stock_topics_combined(symbol)
            topics = [item.to_dict() for item in combined.topics]
            details: list[dict[str, Any]] = []
            for info in combined.topics[:5]:
                if not info.topic_id:
                    continue
                try:
                    detail = self._adapter.get_topic_compare(symbol, info.topic_id)
                    details.append(detail.to_dict())
                except Exception:
                    continue
            return {
                'symbol': symbol,
                'topic_ids': [item.topic_id for item in combined.topics],
                'hot_topics': topics,
                'topic_details': details,
                'topics': topics,
                'count': combined.count,
                'source': self.source_name,
            }
        return self._execute_with_cache('topics', symbol, _produce)

    def list_sectors_market(
        self,
        category: str,
        sort_by: str = "涨幅",
        count: int = 100,
        ascending: bool = False,
        start: int = 0,
    ) -> dict[str, Any]:
        """按分类拉板块 / 个股行情（统一分发器）。

        支持：
          - ``沪深A股`` / ``6`` / ``A股`` / ``全部`` / ``all`` → 走 ``list_by_category``
          - ``行业指数`` / ``行业`` / ``industry`` → 走 32 个申万行业指数 K 线
          - ``概念指数`` / ``概念`` / ``concept`` → 走 50 个常用概念主题指数 K 线

        其余传参（如 ``行业板块``）会抛 ValueError。
        """
        text = str(category or "").strip()
        if text in _INDUSTRY_ALIASES:
            return self.list_industry_sectors_market(
                sort_by=sort_by, count=count, ascending=ascending, start=start
            )
        if text in _CONCEPT_ALIASES:
            return self.list_concept_sectors_market(
                sort_by=sort_by, count=count, ascending=ascending, start=start
            )
        # 默认走 list_by_category 路径
        category_id = _normalize_category_id(category)
        def _produce() -> dict[str, Any]:
            payload: SectorMarket = self._adapter.list_sectors_market(
                category_id, sort_by=sort_by, count=count, ascending=ascending, start=start
            )
            return payload.to_dict()
        cache_key = f'c-{category_id}-{sort_by}-{ascending}-{start}-{count}'
        return self._execute_with_cache('sectors_market', cache_key, _produce)

    def list_industry_sectors_market(
        self,
        sort_by: str = "涨幅",
        count: int = 100,
        ascending: bool = False,
        start: int = 0,
    ) -> dict[str, Any]:
        """所有 32 个申万行业指数的当日行情（涨幅 / 成交额 / 量 / 振幅）。"""
        def _produce() -> dict[str, Any]:
            payload: SectorMarket = self._adapter.get_industry_sectors_market(
                sort_by=sort_by, count=count, ascending=ascending, start=start
            )
            return payload.to_dict()
        cache_key = f'i-{sort_by}-{ascending}-{start}-{count}'
        return self._execute_with_cache('industry_sectors_market', cache_key, _produce)

    def list_concept_sectors_market(
        self,
        sort_by: str = "涨幅",
        count: int = 100,
        ascending: bool = False,
        start: int = 0,
    ) -> dict[str, Any]:
        """所有 ~50 个常用概念主题指数的当日行情。"""
        def _produce() -> dict[str, Any]:
            payload: SectorMarket = self._adapter.get_concept_sectors_market(
                sort_by=sort_by, count=count, ascending=ascending, start=start
            )
            return payload.to_dict()
        cache_key = f'x-{sort_by}-{ascending}-{start}-{count}'
        return self._execute_with_cache('concept_sectors_market', cache_key, _produce)

    def get_theme_market(self, symbol: str, req_id: str = "200743") -> dict[str, Any]:
        def _produce() -> dict[str, Any]:
            theme: ThemeMarket = self._adapter.get_theme_market(symbol, req_id=req_id)
            return theme.to_dict()
        return self._execute_with_cache('theme_market', f'{symbol}-{req_id}', _produce)

    def count_limit_up_down(
        self,
        *,
        category: str = "沪深A股",
        max_pages: int = 80,
        trade_date: str | None = None,
    ) -> dict[str, Any]:
        def _produce() -> dict[str, Any]:
            payload: LimitUpDownCount = self._adapter.count_limit_up_down(
                category=category,
                max_pages=max_pages,
                trade_date=trade_date,
            )
            return payload.to_dict()
        return self._execute_with_cache('limit_count', category, _produce)

    def compute_turnover_rate_series(
        self,
        symbol: str,
        target_type: str,
        period: str = "1d",
        adjust: str = "qfq",
    ) -> dict[str, Any]:
        def _produce() -> dict[str, Any]:
            payload: TurnoverRateSeries = self._adapter.compute_turnover_rate_series(
                symbol, target_type, period=period, adjust=adjust
            )
            return payload.to_dict()
        return self._execute_with_cache(
            'turnover', f'{target_type}-{symbol}-{period}-{adjust}', _produce
        )

    def get_stock_info(self, symbol: str, target_type: str = "stock") -> dict[str, Any]:
        """单只股票 F10 基础信息。默认 ``target_type="stock"``，同时把已持久化的
        turnover 快照注入响应（来自 :mod:`backend.services.stock.turnover_repo`）。"""
        from backend.services.stock.turnover_repo import attach_to_stock_info

        def _produce() -> dict[str, Any]:
            payload = self._adapter.get_stock_info(symbol).to_dict()
            # 注入 turnover（不再每次调 eltdx，直接读本地 repo）
            attach_to_stock_info(payload, target_type, symbol)
            return payload
        return self._execute_with_cache('stock_info', f'{target_type}-{symbol}', _produce)

    def get_company_profile(self, symbol: str, section: str = "8") -> dict[str, Any]:
        def _produce() -> dict[str, Any]:
            return self._adapter.get_company_profile(symbol, section=section).to_dict()
        return self._execute_with_cache('company_profile', f'{symbol}-{section}', _produce)

    def get_business_composition(
        self, symbol: str, report_date: str | None = None
    ) -> dict[str, Any]:
        def _produce() -> dict[str, Any]:
            return self._adapter.get_business_composition(symbol, report_date=report_date).to_dict()
        key = f'{symbol}-{report_date or "latest"}'
        return self._execute_with_cache('business_composition', key, _produce)

    def get_valuation(self, symbol: str, req_id: str = "200191") -> dict[str, Any]:
        def _produce() -> dict[str, Any]:
            return self._adapter.get_valuation(symbol, req_id=req_id).to_dict()
        return self._execute_with_cache('valuation', f'{symbol}-{req_id}', _produce)

    def get_finance_report(self, symbol: str, report_type: str = "zcfzb") -> dict[str, Any]:
        def _produce() -> dict[str, Any]:
            return self._adapter.get_finance_report(symbol, report_type=report_type).to_dict()
        return self._execute_with_cache('finance_report', f'{symbol}-{report_type}', _produce)

    def get_finance_diagnosis(self, symbol: str, section: str = "yynl") -> dict[str, Any]:
        def _produce() -> dict[str, Any]:
            return self._adapter.get_finance_diagnosis(symbol, section=section).to_dict()
        return self._execute_with_cache('finance_diagnosis', f'{symbol}-{section}', _produce)

    def get_stock_score(self, symbol: str, section: str = "pf") -> dict[str, Any]:
        def _produce() -> dict[str, Any]:
            return self._adapter.get_stock_score(symbol, section=section).to_dict()
        return self._execute_with_cache('stock_score', f'{symbol}-{section}', _produce)

    def get_profit_forecast(self, symbol: str) -> dict[str, Any]:
        def _produce() -> dict[str, Any]:
            return self._adapter.get_profit_forecast(symbol).to_dict()
        return self._execute_with_cache('profit_forecast', symbol, _produce)

    def get_ranking_detail(self, symbol: str, section: str = "scpmdela") -> dict[str, Any]:
        def _produce() -> dict[str, Any]:
            return self._adapter.get_ranking_detail(symbol, section=section).to_dict()
        return self._execute_with_cache('ranking_detail', f'{symbol}-{section}', _produce)

    def get_governance(self, symbol: str, section: str = "wgcl") -> dict[str, Any]:
        def _produce() -> dict[str, Any]:
            return self._adapter.get_governance(symbol, section=section).to_dict()
        return self._execute_with_cache('governance', f'{symbol}-{section}', _produce)

    # -------- 公告 / 新闻 / 路演 / 研报 --------

    def get_announcements(self, symbol: str) -> dict[str, Any]:
        def _produce() -> dict[str, Any]:
            return self._adapter.get_announcements(symbol).to_dict()
        return self._execute_with_cache('announcements', symbol, _produce)

    def get_news(self, symbol: str) -> dict[str, Any]:
        def _produce() -> dict[str, Any]:
            return self._adapter.get_news(symbol).to_dict()
        return self._execute_with_cache('news', symbol, _produce)

    def get_roadshows(self, symbol: str) -> dict[str, Any]:
        def _produce() -> dict[str, Any]:
            return self._adapter.get_roadshows(symbol).to_dict()
        return self._execute_with_cache('roadshows', symbol, _produce)

    def get_company_news(self, symbol: str, section: str = "gsyj") -> dict[str, Any]:
        def _produce() -> dict[str, Any]:
            return self._adapter.get_company_news(symbol, section=section).to_dict()
        return self._execute_with_cache('company_news', f'{symbol}-{section}', _produce)

    def ping(self) -> dict[str, Any]:
        try:
            return self._adapter.ping()
        except Exception as exc:  # pragma: no cover
            return {"source": self.source_name, "ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# 单例访问
# ---------------------------------------------------------------------------

_singleton: FundamentalsService | None = None
_singleton_lock = RLock()


def get_fundamentals_service() -> FundamentalsService:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = FundamentalsService()
        return _singleton


def reset_fundamentals_service() -> None:
    global _singleton
    with _singleton_lock:
        _singleton = None
