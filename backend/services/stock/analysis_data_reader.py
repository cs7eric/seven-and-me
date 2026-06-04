from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from backend.config.settings import STOCK_REFERENCE_CACHE_FOLDER
from backend.utils.json_io import read_json_file


@dataclass
class ReadResult:
    data: Any
    source: str = "unknown"
    ok: bool = True
    warnings: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_source_meta(self) -> dict[str, Any]:
        payload = {
            "source": self.source,
            "ok": self.ok,
        }
        if self.warnings:
            payload["warnings"] = self.warnings
        if self.meta:
            payload.update(self.meta)
        return payload


class StockAnalysisDataReader(Protocol):
    """Abstract data reader used by AI feature-summary builders.

    Implementations may read live adapters, local cache, a database, or a test
    fixture. Feature builders should depend on this protocol, not on any single
    market-data vendor.
    """

    def read_auction(self, symbol: str) -> ReadResult: ...

    def read_klines(self, target_type: str, symbol: str, period: str, adjust: str) -> ReadResult: ...

    def read_turnover(self, target_type: str, symbol: str) -> ReadResult: ...

    def read_breadth_latest(self) -> ReadResult: ...

    def read_breadth_series(self, limit: int = 180) -> ReadResult: ...

    def read_stock_meta(self, target_type: str, symbol: str) -> ReadResult: ...

    def read_fundamentals_bundle(self, symbol: str, target_type: str = "stock") -> ReadResult: ...

    def read_sector_market(self, category: str, count: int = 80) -> ReadResult: ...


def _safe_warning(prefix: str, exc: Exception) -> str:
    return f"{prefix}: {exc}"


def _cache_klines_payload(target_type: str, symbol: str, period: str, adjust: str) -> dict[str, Any] | None:
    from backend.repositories.stock.workspace_repo import read_cached_stock_klines

    items = read_cached_stock_klines(target_type, symbol, period, adjust)
    if not items:
        return None
    return {
        "symbol": symbol,
        "target_type": target_type,
        "period": period,
        "adjust": adjust,
        "items": items,
    }


class DefaultStockAnalysisDataReader:
    """Default reader backed by the project's existing stock services."""

    def read_auction(self, symbol: str) -> ReadResult:
        cache_file = STOCK_REFERENCE_CACHE_FOLDER / "auction" / f"{symbol}.json"
        warnings: list[str] = []
        try:
            from backend.services.stock.auction_service import fetch_stock_auction

            return ReadResult(fetch_stock_auction(symbol), source="service:auction", ok=True)
        except Exception as exc:
            warnings.append(_safe_warning("auction live fetch failed", exc))
            cached = read_json_file(cache_file, None)
            if isinstance(cached, dict):
                return ReadResult(cached, source="cache:auction", ok=True, warnings=warnings, meta={"stale": True})
            return ReadResult({}, source="none", ok=False, warnings=warnings)

    def read_klines(self, target_type: str, symbol: str, period: str, adjust: str) -> ReadResult:
        warnings: list[str] = []
        try:
            from backend.services.stock.kline_service import resolve_stock_klines
            from backend.services.stock.sample_data_service import sample_stock_klines

            items, source = resolve_stock_klines(target_type, symbol, period, adjust, sample_stock_klines)
            return ReadResult(items, source=f"service:kline:{source}", ok=True, meta={"period": period, "adjust": adjust})
        except Exception as exc:
            warnings.append(_safe_warning(f"kline {period}/{adjust} fetch failed", exc))
            cached = _cache_klines_payload(target_type, symbol, period, adjust)
            if cached:
                return ReadResult(cached.get("items") or [], source="cache:kline", ok=True, warnings=warnings, meta={"period": period, "adjust": adjust, "stale": True})
            return ReadResult([], source="none", ok=False, warnings=warnings, meta={"period": period, "adjust": adjust})

    def read_turnover(self, target_type: str, symbol: str) -> ReadResult:
        from backend.services.stock.turnover_repo import load_turnover

        payload = load_turnover(target_type, symbol)
        if payload:
            return ReadResult(payload, source="repo:turnover", ok=True)
        legacy_file = STOCK_REFERENCE_CACHE_FOLDER / "f10" / "turnover" / f"{target_type}-{symbol}-1d-qfq.json"
        legacy = read_json_file(legacy_file, None)
        if isinstance(legacy, dict):
            return ReadResult(legacy, source="cache:f10_turnover", ok=True, meta={"legacy": True})
        return ReadResult({}, source="none", ok=False, warnings=["turnover cache missing"])

    def read_breadth_latest(self) -> ReadResult:
        cache_file = STOCK_REFERENCE_CACHE_FOLDER / "breadth" / "latest.json"
        warnings: list[str] = []
        try:
            from backend.adapters.market.eastmoney import fetch_market_breadth

            data = fetch_market_breadth()
            if data:
                return ReadResult(data, source="service:breadth", ok=True)
        except Exception as exc:
            warnings.append(_safe_warning("breadth live fetch failed", exc))
        cached = read_json_file(cache_file, None)
        if isinstance(cached, dict):
            return ReadResult(cached, source="cache:breadth", ok=True, warnings=warnings, meta={"stale": True})
        return ReadResult({}, source="none", ok=False, warnings=warnings)

    def read_breadth_series(self, limit: int = 180) -> ReadResult:
        cache_file = STOCK_REFERENCE_CACHE_FOLDER / "breadth" / "series.json"
        payload = read_json_file(cache_file, [])
        if not isinstance(payload, list):
            return ReadResult([], source="none", ok=False, warnings=["breadth series cache is not a list"])
        return ReadResult(payload[-max(1, limit):], source="cache:breadth_series", ok=True, meta={"kept": min(len(payload), max(1, limit)), "total": len(payload)})

    def read_stock_meta(self, target_type: str, symbol: str) -> ReadResult:
        try:
            from backend.adapters.market.eastmoney import fetch_stock_meta

            data = fetch_stock_meta(target_type, symbol)
            return ReadResult(data, source="service:stock_meta", ok=True)
        except Exception as exc:
            return ReadResult({}, source="none", ok=False, warnings=[_safe_warning("stock meta fetch failed", exc)])

    def read_fundamentals_bundle(self, symbol: str, target_type: str = "stock") -> ReadResult:
        if target_type != "stock":
            return ReadResult({}, source="none", ok=False, warnings=["fundamentals skipped for non-stock target"])

        warnings: list[str] = []
        bundle: dict[str, Any] = {}
        try:
            from backend.services.stock.f10 import get_fundamentals_service

            service = get_fundamentals_service()
        except Exception as exc:
            return ReadResult({}, source="none", ok=False, warnings=[_safe_warning("fundamentals service import failed", exc)])

        calls = {
            "stock_info": lambda: service.get_stock_info(symbol, target_type=target_type),
            "topics": lambda: service.get_stock_topics(symbol),
            "business_composition": lambda: service.get_business_composition(symbol),
            "valuation": lambda: service.get_valuation(symbol),
            "profit_forecast": lambda: service.get_profit_forecast(symbol),
            "theme_market": lambda: service.get_theme_market(symbol),
        }
        finance_sections = {
            "finance_report_balance": lambda: service.get_finance_report(symbol, report_type="zcfzb"),
            "finance_report_income": lambda: service.get_finance_report(symbol, report_type="lrb"),
            "finance_report_cashflow": lambda: service.get_finance_report(symbol, report_type="xjllb"),
            "finance_diagnosis_profit": lambda: service.get_finance_diagnosis(symbol, section="hlnl"),
            "finance_diagnosis_growth": lambda: service.get_finance_diagnosis(symbol, section="cznl"),
            "finance_diagnosis_cashflow": lambda: service.get_finance_diagnosis(symbol, section="xjll"),
            "stock_score": lambda: service.get_stock_score(symbol, section="pf"),
            "ranking_detail": lambda: service.get_ranking_detail(symbol),
            "governance": lambda: service.get_governance(symbol),
        }
        calls.update(finance_sections)

        for key, producer in calls.items():
            try:
                payload = producer()
                if payload:
                    bundle[key] = payload
            except Exception as exc:
                warnings.append(_safe_warning(f"fundamental {key} failed", exc))

        return ReadResult(bundle, source=f"service:f10:{service.source_name}", ok=bool(bundle), warnings=warnings)

    def read_sector_market(self, category: str, count: int = 80) -> ReadResult:
        try:
            from backend.services.stock.f10 import get_fundamentals_service

            service = get_fundamentals_service()
            data = service.list_sectors_market(category, count=count)
            return ReadResult(data, source=f"service:f10:{service.source_name}", ok=True, meta={"category": category, "count": count})
        except Exception as exc:
            return ReadResult({}, source="none", ok=False, warnings=[_safe_warning(f"sector market {category} failed", exc)])


def create_default_stock_analysis_data_reader() -> StockAnalysisDataReader:
    return DefaultStockAnalysisDataReader()
