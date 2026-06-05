from backend.adapters.market.common import build_volume_ratio, parse_stock_trade_timestamp
from backend.config.settings import DOWNLOAD_HEADERS, STOCK_TENCENT_KLINE_URL
import requests


def stock_symbol_to_tencent_code(target_type: str, symbol: str) -> str:
    if target_type == 'index':
        if symbol.startswith('399'):
            return f'sz{symbol}'
        return f'sh{symbol}'
    return f'sh{symbol}' if symbol.startswith(('5', '6', '9')) else f'sz{symbol}'


def stock_period_to_tencent_unit(period: str) -> str:
    period_map = {
        '1m': 'm1',
        '5m': 'm5',
        '15m': 'm15',
        '30m': 'm30',
        '60m': 'm60',
        '120m': 'm120',
        '1d': 'day',
        '1w': 'week',
    }
    return period_map.get(period, 'day')


def stock_adjust_to_tencent_prefix(adjust: str) -> str:
    if adjust == 'qfq':
        return 'qfq'
    if adjust == 'hfq':
        return 'hfq'
    return ''


def parse_tencent_kline_rows(rows: list[list[str]], target_type: str) -> list[dict]:
    items: list[dict] = []
    previous_volume = None
    volumes_window: list[float] = []
    is_index = target_type == 'index'
    for row in rows:
        if len(row) < 6:
            continue
        try:
            trade_time = parse_stock_trade_timestamp(str(row[0]))
            volume = float(row[5] or 0)
            turnover = float(row[36] or 0) if len(row) > 36 and row[36] else 0
            turnover_rate = float(row[37] or 0) if len(row) > 37 and row[37] else 0
            if is_index and turnover <= 0 and len(row) > 37 and row[37]:
                turnover = float(row[37] or 0)
            volume_ratio = build_volume_ratio(volume, previous_volume, volumes_window)
            previous_volume = volume
            items.append({
                'timestamp': int(trade_time.timestamp() * 1000),
                'trade_date': trade_time.strftime('%Y-%m-%d'),
                'open': float(row[1] or 0),
                'close': float(row[2] or 0),
                'high': float(row[3] or 0),
                'low': float(row[4] or 0),
                'volume': volume,
                'turnover': turnover,
                'volume_ratio': volume_ratio,
                'turnover_rate': turnover_rate,
            })
        except ValueError:
            continue
    return items


def fetch_stock_klines_from_tencent(target_type: str, symbol: str, period: str, adjust: str) -> list[dict]:
    code = stock_symbol_to_tencent_code(target_type, symbol)
    unit = stock_period_to_tencent_unit(period)
    adjust_prefix = stock_adjust_to_tencent_prefix(adjust)
    params = {'param': f'{code},{unit},,,500,{adjust_prefix}'}
    response = requests.get(
        STOCK_TENCENT_KLINE_URL,
        params=params,
        headers={'User-Agent': DOWNLOAD_HEADERS['User-Agent']},
        timeout=(5, 12),
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get('data') or {}
    target_data = data.get(code) or {}
    candidates = []
    if adjust_prefix:
        candidates.append(f'{adjust_prefix}{unit}')
    candidates.append(unit)
    rows = []
    for key in candidates:
        value = target_data.get(key)
        if isinstance(value, list) and value:
            rows = value
            break
    items = parse_tencent_kline_rows(rows, target_type)
    if items:
        return items
    raise ValueError('腾讯K线接口未返回有效数据')
