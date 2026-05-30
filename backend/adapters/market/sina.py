from backend.adapters.market.common import build_volume_ratio, parse_stock_trade_timestamp
from backend.config.settings import DOWNLOAD_HEADERS, STOCK_SINA_MINUTE_KLINE_URL
import requests


def stock_symbol_to_sina_code(target_type: str, symbol: str) -> str:
    if target_type == 'index':
        if symbol.startswith('399'):
            return f'sz{symbol}'
        return f'sh{symbol}'
    return f'sh{symbol}' if symbol.startswith(('5', '6', '9')) else f'sz{symbol}'


def fetch_stock_klines_from_sina(target_type: str, symbol: str, period: str, adjust: str) -> list[dict]:
    if period not in {'5m', '15m', '30m', '60m'}:
        raise ValueError('新浪分钟K线仅支持 5/15/30/60 分钟')
    code = stock_symbol_to_sina_code(target_type, symbol)
    scale = int(period.replace('m', ''))
    response = requests.get(
        STOCK_SINA_MINUTE_KLINE_URL,
        params={
            'symbol': code,
            'scale': scale,
            'ma': 'no',
            'datalen': 500,
        },
        headers={'User-Agent': DOWNLOAD_HEADERS['User-Agent'], 'Referer': 'https://finance.sina.com.cn/'},
        timeout=(5, 12),
    )
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list) or not rows:
        raise ValueError('新浪分钟K线接口未返回有效数据')

    items: list[dict] = []
    previous_volume = None
    volumes_window: list[float] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            trade_time = parse_stock_trade_timestamp(str(row.get('day') or ''))
            volume = float(row.get('volume') or 0)
            volume_ratio = build_volume_ratio(volume, previous_volume, volumes_window)
            previous_volume = volume
            items.append({
                'timestamp': int(trade_time.timestamp() * 1000),
                'open': float(row.get('open') or 0),
                'close': float(row.get('close') or 0),
                'high': float(row.get('high') or 0),
                'low': float(row.get('low') or 0),
                'volume': volume,
                'turnover': float(row.get('amount') or 0),
                'volume_ratio': volume_ratio,
            })
        except ValueError:
            continue
    if items:
        return items
    raise ValueError('新浪分钟K线解析失败')
