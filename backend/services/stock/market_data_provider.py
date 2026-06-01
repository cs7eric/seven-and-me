from __future__ import annotations

from typing import Protocol

from backend.adapters.market.eastmoney import fetch_market_breadth, fetch_stock_klines_from_eastmoney, fetch_stock_meta
from backend.adapters.market.mootdx_adapter import fetch_stock_klines_from_mootdx, is_minute_stock_period
from backend.adapters.market.sina import fetch_stock_klines_from_sina
from backend.adapters.market.tencent import fetch_stock_klines_from_tencent
from backend.config.settings import STOCK_REFERENCE_CACHE_FOLDER
from backend.repositories.stock.workspace_repo import read_cached_stock_klines
from backend.services.stock.config_service import get_stock_chart_config
from backend.utils.json_io import read_json_file, write_json_file


class MarketDataProvider(Protocol):

    def fetch_index_bars(self, symbol: str) -> tuple[list[dict], dict]: ...

    def fetch_breadth(self) -> dict: ...

    def fetch_stock_meta(self, target_type: str, symbol: str) -> dict: ...


def _get_klines_with_fallback(target_type: str, symbol: str, period: str, adjust: str) -> tuple[list[dict], dict]:
    providers = {
        'mootdx': fetch_stock_klines_from_mootdx,
        'sina': fetch_stock_klines_from_sina,
        'tencent': fetch_stock_klines_from_tencent,
        'eastmoney': fetch_stock_klines_from_eastmoney,
    }
    kline_config = get_stock_chart_config().get('kline', {})
    if period == '1w':
        primary = str(kline_config.get('weekly_provider', 'tencent'))
        fallbacks = kline_config.get('fallbacks', {}).get('weekly', [])
    elif is_minute_stock_period(period):
        primary = str(kline_config.get('minute_provider', 'mootdx'))
        fallbacks = kline_config.get('fallbacks', {}).get('minute', [])
    else:
        primary = str(kline_config.get('daily_provider', 'tencent'))
        fallbacks = kline_config.get('fallbacks', {}).get('daily', [])

    plan: list[str] = []
    for item in [primary, *(fallbacks if isinstance(fallbacks, list) else [])]:
        key = str(item).strip()
        if key and key not in plan:
            plan.append(key)

    for provider_name in plan:
        provider = providers.get(provider_name)
        if not provider:
            continue
        try:
            items = provider(target_type, symbol, period, adjust)
            if items:
                return items, {'source': provider_name, 'stale': False, 'dataQuality': 'ok'}
        except Exception:
            continue

    cached_items = read_cached_stock_klines(target_type, symbol, period, adjust)
    if cached_items:
        return cached_items, {'source': 'cache', 'stale': True, 'dataQuality': 'stale'}

    return [], {'source': 'none', 'stale': True, 'dataQuality': 'error'}


def _get_breadth_with_fallback() -> dict:
    cache_file = STOCK_REFERENCE_CACHE_FOLDER / 'breadth' / 'latest.json'
    last_error = None

    try:
        data = fetch_market_breadth()
        if data:
            return {'data': data, 'source': 'eastmoney', 'stale': False, 'dataQuality': 'ok'}
    except Exception as exc:
        last_error = str(exc)

    cached = read_json_file(cache_file, None)
    if cached and isinstance(cached, dict):
        return {'data': cached, 'source': 'cache', 'stale': True, 'dataQuality': 'stale'}

    return {'data': {}, 'source': 'none', 'stale': True, 'dataQuality': 'error', 'error': last_error}


def _get_stock_meta_with_fallback(target_type: str, symbol: str) -> tuple[dict, dict]:
    try:
        meta = fetch_stock_meta(target_type, symbol)
        return meta, {'source': 'eastmoney', 'stale': False, 'dataQuality': 'ok'}
    except Exception:
        return {'error': 'unavailable', 'symbol': symbol, 'capStyle': None, 'sectorIndexSymbol': None, 'sectorIndexName': None}, {'source': 'none', 'stale': True, 'dataQuality': 'error'}


def create_market_data_provider() -> MarketDataProvider:

    class _Impl:

        def fetch_index_bars(self, symbol: str) -> tuple[list[dict], dict]:
            result, meta = _get_klines_with_fallback('index', symbol, '1d', 'qfq')
            meta['updatedAt'] = None
            return result, meta

        def fetch_breadth(self) -> dict:
            return _get_breadth_with_fallback()

        def fetch_stock_meta(self, target_type: str, symbol: str) -> dict:
            result, meta = _get_stock_meta_with_fallback(target_type, symbol)
            result['_source'] = meta
            return result

    return _Impl()


market_data_provider = create_market_data_provider()
