from backend.adapters.market.common import build_volume_ratio, parse_stock_trade_timestamp
from backend.services.stock.config_service import get_stock_chart_config
from mootdx.quotes import StdQuotes


def is_minute_stock_period(period: str) -> bool:
    return period in {'1m', '5m', '15m', '30m', '60m', '120m'}


def fetch_stock_klines_from_mootdx(target_type: str, symbol: str, period: str, adjust: str) -> list[dict]:
    if target_type == 'sector':
        raise ValueError('mootdx 不支持板块分钟K线')
    config_data = get_stock_chart_config().get('kline', {})
    mootdx_config = config_data.get('mootdx', {}) if isinstance(config_data, dict) else {}
    minute_adjust_mode = str(mootdx_config.get('minute_adjust_mode', 'none_only'))
    if is_minute_stock_period(period) and minute_adjust_mode == 'none_only' and adjust != 'none':
        raise ValueError('当前 mootdx 分钟K线仅支持不复权')

    frequency_map = {
        '1m': '1m',
        '5m': '5m',
        '15m': '15m',
        '30m': '30m',
        '60m': '1h',
        '1d': 'day',
        '1w': 'week',
    }
    frequency = frequency_map.get(period)
    if not frequency:
        raise ValueError(f'mootdx 暂不支持周期: {period}')

    servers = mootdx_config.get('servers') or []
    timeout = int(mootdx_config.get('timeout', 10) or 10)
    last_error = None
    for server in servers:
        try:
            client = StdQuotes(server=tuple(server), timeout=timeout, raise_exception=True)
            fetch_kwargs = {'symbol': symbol, 'frequency': frequency, 'offset': 500}
            if adjust in {'qfq', 'hfq'} and not is_minute_stock_period(period):
                fetch_kwargs['adjust'] = adjust
            data = client.index(symbol=symbol, frequency=frequency, offset=500) if target_type == 'index' else client.bars(**fetch_kwargs)
            if data is None or len(data) == 0:
                continue
            items: list[dict] = []
            previous_volume = None
            volumes_window: list[float] = []
            for _, row in data.iterrows():
                volume = float(row.get('volume') or row.get('vol') or 0)
                turnover = float(row.get('amount') or 0)
                volume_ratio = build_volume_ratio(volume, previous_volume, volumes_window)
                previous_volume = volume
                trade_time = parse_stock_trade_timestamp(str(row.get('datetime') or ''))
                items.append({
                    'timestamp': int(trade_time.timestamp() * 1000),
                    'open': float(row.get('open') or 0),
                    'close': float(row.get('close') or 0),
                    'high': float(row.get('high') or 0),
                    'low': float(row.get('low') or 0),
                    'volume': volume,
                    'turnover': turnover,
                    'volume_ratio': volume_ratio,
                })
            if items:
                return items
        except Exception as exc:
            last_error = exc
            continue
    if last_error:
        raise ValueError(f'mootdx K线请求失败: {last_error}')
    raise ValueError('mootdx K线接口未返回有效数据')
