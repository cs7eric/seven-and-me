from backend.adapters.market.eastmoney import fetch_stock_klines_from_eastmoney
from backend.adapters.market.mootdx_adapter import fetch_stock_klines_from_mootdx, is_minute_stock_period
from backend.adapters.market.sina import fetch_stock_klines_from_sina
from backend.adapters.market.tencent import fetch_stock_klines_from_tencent
from backend.repositories.stock.workspace_repo import read_cached_stock_klines
from backend.services.stock.config_service import get_stock_chart_config


def get_stock_kline_provider_plan(period: str) -> list[str]:
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
    return plan


def resolve_stock_klines(target_type: str, symbol: str, period: str, adjust: str, sample_loader) -> tuple[list[dict], str]:
    providers = {
        'mootdx': fetch_stock_klines_from_mootdx,
        'sina': fetch_stock_klines_from_sina,
        'tencent': fetch_stock_klines_from_tencent,
        'eastmoney': fetch_stock_klines_from_eastmoney,
    }
    for provider_name in get_stock_kline_provider_plan(period):
        provider = providers.get(provider_name)
        if not provider:
            continue
        try:
            items = provider(target_type, symbol, period, adjust)
            if items:
                return items, provider_name
        except Exception:
            continue

    cached_items = read_cached_stock_klines(target_type, symbol, period, adjust)
    if cached_items:
        return cached_items, 'cache'

    if is_minute_stock_period(period):
        raise ValueError('分钟K线真实数据暂不可用')

    return sample_loader(symbol, period), 'sample'
