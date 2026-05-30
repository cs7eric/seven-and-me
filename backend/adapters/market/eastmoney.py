from backend.config.settings import STOCK_EASTMONEY_HEADERS, STOCK_EASTMONEY_KLINE_URL
from backend.adapters.market.common import build_volume_ratio, parse_stock_trade_timestamp
import requests


def stock_period_to_eastmoney_klt(period: str) -> str:
    period_map = {
        '1m': '1',
        '5m': '5',
        '15m': '15',
        '30m': '30',
        '60m': '60',
        '120m': '120',
        '1d': '101',
        '1w': '102',
    }
    return period_map.get(period, '101')


def stock_adjust_to_eastmoney_fqt(adjust: str) -> str:
    if adjust == 'hfq':
        return '2'
    if adjust == 'none':
        return '0'
    return '1'


def eastmoney_secid_candidates(target_type: str, symbol: str) -> list[str]:
    value = (symbol or '').strip().lower()
    if target_type == 'sector':
        return []
    if target_type == 'index':
        if value.startswith(('000', '880')):
            return [f'1.{symbol}', f'0.{symbol}']
        if value.startswith('399'):
            return [f'0.{symbol}', f'1.{symbol}']
        return [f'1.{symbol}', f'0.{symbol}']
    if symbol.startswith(('5', '6', '9')):
        return [f'1.{symbol}', f'0.{symbol}']
    return [f'0.{symbol}', f'1.{symbol}']


def parse_eastmoney_kline_rows(rows: list[str]) -> list[dict]:
    items: list[dict] = []
    previous_volume = None
    volumes_window: list[float] = []
    for row in rows:
        parts = row.split(',')
        if len(parts) < 7:
            continue
        try:
            trade_time = parse_stock_trade_timestamp(parts[0])
            volume = float(parts[5] or 0)
            turnover = float(parts[6] or 0)
            turnover_rate = float(parts[10] or 0) if len(parts) > 10 and parts[10] else 0
            volume_ratio = build_volume_ratio(volume, previous_volume, volumes_window)
            previous_volume = volume
            items.append({
                'timestamp': int(trade_time.timestamp() * 1000),
                'open': float(parts[1] or 0),
                'close': float(parts[2] or 0),
                'high': float(parts[3] or 0),
                'low': float(parts[4] or 0),
                'volume': volume,
                'turnover': turnover,
                'volume_ratio': volume_ratio,
                'turnover_rate': turnover_rate,
            })
        except ValueError:
            continue
    return items


def fetch_stock_klines_from_eastmoney(target_type: str, symbol: str, period: str, adjust: str) -> list[dict]:
    candidates = eastmoney_secid_candidates(target_type, symbol)
    if not candidates:
        return []

    params = {
        'fields1': 'f1,f2,f3,f4,f5,f6',
        'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
        'ut': 'fa5fd1943c7b386f172d6893dbfba10b',
        'klt': stock_period_to_eastmoney_klt(period),
        'fqt': stock_adjust_to_eastmoney_fqt(adjust),
        'beg': '20180101',
        'end': '20500101',
        'lmt': '500',
    }

    session = requests.Session()
    session.trust_env = False
    last_error = None
    for secid in candidates:
        try:
            response = session.get(
                STOCK_EASTMONEY_KLINE_URL,
                params={**params, 'secid': secid},
                headers=STOCK_EASTMONEY_HEADERS,
                timeout=(5, 12),
                proxies={'http': None, 'https': None},
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get('data') or {}
            rows = data.get('klines') or []
            items = parse_eastmoney_kline_rows(rows)
            if items:
                return items
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            continue
    if last_error:
        raise ValueError(f'东方财富K线请求失败: {last_error}')
    raise ValueError('东方财富K线接口未返回有效数据')
