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


def fetch_tencent_snapshots(codes: list[str]) -> dict[str, dict]:
    """腾讯 qt.gtimg.cn 批量实时快照 (覆盖 A 股全市场, 不像 eltdx list_by_category(6) 那样只返 Top 排序截断).

    :param codes: ``sh600519`` / ``sz000001`` / ``bj830799`` 形式的 codes
    :return: ``{code: {name, last_price, pre_close_price, change_pct, open, high, low, volume, turnover}}``
             涨跌幅优先用接口 field[32], 缺失时回退 ``(last - pre_close) / pre_close``.
             单只解析失败/被排除时该 code 不会出现在结果里 (调用方应按"在 dict 里就有数据"判断).

    限流: 每批最多 500 个 code, 间隔 0.22s; 全市场约 5000+ 只也只要 ~12 批 / ~3s.
    """
    import urllib.request
    import time
    out: dict[str, dict] = {}
    if not codes:
        return out
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    opener.addheaders = [
        ('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'),
        ('Referer', 'https://gu.qq.com/'),
    ]
    for i in range(0, len(codes), 500):
        batch = codes[i:i + 500]
        url = 'https://qt.gtimg.cn/q=' + ','.join(batch)
        try:
            resp = opener.open(url, timeout=10)
            body = resp.read().decode('gbk', errors='ignore')
        except Exception:
            time.sleep(0.22)
            continue
        for line in body.strip().split(';'):
            if '~' not in line:
                continue
            parts = line.split('~')
            if len(parts) < 5:
                continue
            market_marker = parts[0].strip()
            true_code = parts[2].strip() if len(parts) > 2 else ''
            if not true_code:
                continue
            if market_marker.startswith('v_sh'):
                full_code = 'sh' + true_code
            elif market_marker.startswith('v_sz'):
                full_code = 'sz' + true_code
            elif market_marker.startswith('v_bj'):
                full_code = 'bj' + true_code
            else:
                full_code = true_code
            name = parts[1].strip() if len(parts) > 1 else ''
            try:
                last = float(parts[3])
                pre_close = float(parts[4])
            except (TypeError, ValueError):
                last = 0.0
                pre_close = 0.0
            open_ = float(parts[5]) if len(parts) > 5 and parts[5] else None
            volume = float(parts[6]) if len(parts) > 6 and parts[6] else None  # 手
            high = float(parts[33]) if len(parts) > 33 and parts[33] else None
            low = float(parts[34]) if len(parts) > 34 and parts[34] else None
            turnover = float(parts[37]) if len(parts) > 37 and parts[37] else None  # 元
            # field[44] = 流通市值 (亿元), 转成元便于板块加权
            circulating_market_cap = float(parts[44]) * 1e8 if len(parts) > 44 and parts[44] else None
            # field[32] = 涨跌幅% (e.g. 1.23); 缺失则用 last/pre_close 算
            pct: float | None = None
            if len(parts) > 32 and parts[32]:
                try:
                    pct = float(parts[32])
                except (TypeError, ValueError):
                    pct = None
            if pct is None and pre_close:
                pct = (last - pre_close) / pre_close * 100.0
            out[full_code] = {
                'name': name,
                'last_price': last or None,
                'pre_close_price': pre_close or None,
                'change_pct': pct,
                'open': open_,
                'high': high,
                'low': low,
                'volume': volume,
                'turnover': turnover,
                'circulating_market_cap': circulating_market_cap,
            }
        if i + 500 < len(codes):
            time.sleep(0.22)
    return out
