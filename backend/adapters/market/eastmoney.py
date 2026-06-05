from backend.config.settings import STOCK_EASTMONEY_HEADERS, STOCK_EASTMONEY_KLINE_URL
from backend.adapters.market.common import build_volume_ratio, parse_stock_trade_timestamp
from backend.services.stock.search_service import resolve_industry_index
import os
import re
import requests

try:
    import akshare as ak
except Exception:
    ak = None


CFI_MARKET_BREADTH_URL = 'https://gg.cfi.cn/cfi_datacontent_server.aspx?ndk=A0A1934A1935A58&client=pc'
CFI_MARKET_BREADTH_REFERER = 'https://gg.cfi.cn/data_ndkA0A1934A1935A58.html'
TENCENT_QUOTE_URL = 'https://qt.gtimg.cn/q={code}'

INDUSTRY_INDEX_SYMBOL_MAP = {
    '银行': '上证50',
    '证券': '沪深300',
    '保险': '沪深300',
    '白酒': '上证50',
    '酿酒': '上证50',
    '食品饮料': '上证50',
    '家用电器': '沪深300',
    '煤炭': '沪深300',
    '石油': '沪深300',
    '电力': '沪深300',
    '公用事业': '沪深300',
    '电网': '沪深300',
    '地产': '沪深300',
    '房地产': '沪深300',
    '建筑': '沪深300',
    '建材': '沪深300',
    '有色': '沪深300',
    '钢铁': '沪深300',
    '化工': '沪深300',
    '医药': '创业板指',
    '生物': '创业板指',
    '医疗': '创业板指',
    '半导体': '科创50',
    '芯片': '科创50',
    '软件': '科创50',
    '通信': '科创50',
    '电子': '科创50',
    '计算机': '科创50',
    '人工智能': '科创50',
    'ai': '科创50',
    '机器人': '科创50',
    '自动化设备': '科创50',
    '新能源': '创业板指',
    '电池': '创业板指',
    '光伏': '创业板指',
    '储能': '创业板指',
    '风电': '创业板指',
    '汽车': '中证500',
    '汽车零部件': '中证500',
    '军工': '中证500',
    '机械': '中证500',
    '物流': '中证500',
    '航运': '中证500',
    '港口': '中证500',
    '零售': '中证500',
    '商贸': '中证500',
    '纺织服饰': '中证1000',
    '农林牧渔': '中证1000',
    '环保': '中证1000',
    '传媒': '中证1000',
    '文化传媒': '中证1000',
    '旅游': '中证1000',
    '酒店': '中证1000',
}


NAME_INDUSTRY_KEYWORDS = {
    '平安银行': '银行',
    '招商银行': '银行',
    '贵州茅台': '白酒',
    '五粮液': '白酒',
    '泸州老窖': '白酒',
    '宁德时代': '新能源',
    '比亚迪': '新能源车',
    '隆基绿能': '光伏',
    '通威股份': '光伏',
    '阳光电源': '储能',
    '恒瑞医药': '医药',
    '药明康德': '医药',
    '迈瑞医疗': '医疗',
    '中际旭创': '通信',
    '中芯国际': '半导体',
    '寒武纪': '人工智能',
    '科大讯飞': '人工智能',
    '工业富联': '电子',
}


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


def tencent_code_for_symbol(target_type: str, symbol: str) -> str:
    if target_type == 'index':
        if symbol.startswith('399'):
            return f'sz{symbol}'
        return f'sh{symbol}'
    return f'sh{symbol}' if symbol.startswith(('5', '6', '9')) else f'sz{symbol}'


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
                'trade_date': trade_time.strftime('%Y-%m-%d'),
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


def eastmoney_secid_for_meta(target_type: str, symbol: str) -> str | None:
    candidates = eastmoney_secid_candidates(target_type, symbol)
    return candidates[0] if candidates else None


def _safe_float(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _without_proxy_env(fn):
    proxy_keys = ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']
    backup = {k: os.environ.get(k) for k in proxy_keys}
    try:
        for k in proxy_keys:
            os.environ.pop(k, None)
        return fn()
    finally:
        for k, v in backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _cap_style_from_market_cap(circ_market_cap: float) -> str | None:
    if circ_market_cap > 500e8:
        return 'large'
    if circ_market_cap > 100e8:
        return 'mid'
    if circ_market_cap > 30e8:
        return 'small'
    if circ_market_cap > 0:
        return 'micro'
    return None


def _normalize_industry_name(industry: str) -> str:
    return str(industry or '').strip().replace(' ', '')


def _sector_index_symbol_from_industry(industry: str) -> str | None:
    normalized = _normalize_industry_name(industry).lower()
    if not normalized:
        return None
    for keyword, symbol in INDUSTRY_INDEX_SYMBOL_MAP.items():
        if keyword.lower() in normalized:
            return symbol
    return None


def _guess_industry_from_name(name: str) -> str:
    clean_name = str(name or '').strip()
    if not clean_name:
        return ''
    for keyword, industry in NAME_INDUSTRY_KEYWORDS.items():
        if keyword in clean_name:
            return industry
    return ''


def _with_industry_index_meta(base: dict) -> dict:
    industry = str(base.get('industry') or '').strip()
    sector_symbol = base.get('sectorIndexSymbol')
    sector_name = base.get('sectorIndexName')

    if not sector_symbol:
        resolved = resolve_industry_index(industry) if industry else None
        if not resolved:
            guessed_industry = _guess_industry_from_name(str(base.get('name') or ''))
            if guessed_industry and not industry:
                industry = guessed_industry
                base['industry'] = guessed_industry
            resolved = resolve_industry_index(industry) if industry else None
        if resolved:
            sector_symbol = resolved.get('sectorIndexSymbol') or None
            sector_name = resolved.get('sectorIndexName') or None
            base['industryQuery'] = resolved.get('industryQuery')

    if not sector_symbol:
        sector_symbol = _sector_index_symbol_from_industry(industry)
        sector_name = sector_name or sector_symbol

    base['sectorIndexSymbol'] = sector_symbol
    base['sectorIndexName'] = sector_name
    return base


def fetch_stock_meta_from_akshare(symbol: str) -> dict:
    if ak is None:
        raise ValueError('AKShare 不可用')

    def _load():
        return ak.stock_zh_a_spot_em()

    df = _without_proxy_env(_load)
    if df is None or df.empty:
        raise ValueError('AKShare A股实时行情为空')

    code_col = '代码' if '代码' in df.columns else None
    if not code_col:
        raise ValueError('AKShare 实时行情缺少代码列')

    row = df[df[code_col].astype(str) == str(symbol)]
    if row.empty:
        raise ValueError(f'AKShare 未找到股票: {symbol}')

    item = row.iloc[0]
    circ_market_cap = _safe_float(item.get('流通市值'))
    total_market_cap = _safe_float(item.get('总市值'))
    industry = item.get('所属行业') if '所属行业' in df.columns else ''
    if industry is None:
        industry = ''

    return _with_industry_index_meta({
        'symbol': str(item.get('代码', symbol)),
        'name': str(item.get('名称', '')),
        'totalMarketCap': total_market_cap,
        'circMarketCap': circ_market_cap,
        'industry': str(industry),
        'capStyle': _cap_style_from_market_cap(circ_market_cap),
        'sectorIndexSymbol': _sector_index_symbol_from_industry(str(industry)),
        'source': 'akshare',
    })


def fetch_stock_meta_from_tencent(symbol: str) -> dict:
    code = tencent_code_for_symbol('stock', symbol)
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        TENCENT_QUOTE_URL.format(code=code),
        headers={
            'User-Agent': STOCK_EASTMONEY_HEADERS.get('User-Agent', 'Mozilla/5.0'),
            'Referer': 'https://gu.qq.com/',
        },
        timeout=(5, 12),
        proxies={'http': None, 'https': None},
    )
    response.raise_for_status()
    match = re.search(r'="([^"]+)"', response.text)
    if not match:
        raise ValueError('腾讯行情接口未返回有效内容')

    parts = match.group(1).split('~')
    if len(parts) < 74:
        raise ValueError('腾讯行情接口字段不足')

    name = parts[1].strip() if len(parts) > 1 else ''
    resolved_symbol = parts[2].strip() if len(parts) > 2 else symbol
    total_market_cap = _safe_float(parts[45]) * 1e8 if len(parts) > 45 else 0.0
    circ_market_cap = _safe_float(parts[44]) * 1e8 if len(parts) > 44 else 0.0

    return _with_industry_index_meta({
        'symbol': resolved_symbol or symbol,
        'name': name,
        'totalMarketCap': total_market_cap,
        'circMarketCap': circ_market_cap,
        'industry': '',
        'capStyle': _cap_style_from_market_cap(circ_market_cap),
        'sectorIndexSymbol': None,
        'source': 'tencent',
    })


def fetch_stock_meta_from_eastmoney(target_type: str, symbol: str) -> dict:
    secid = eastmoney_secid_for_meta(target_type, symbol)
    if not secid:
        raise ValueError(f'无法推断东方财富secid: {target_type}.{symbol}')

    session = requests.Session()
    session.trust_env = False
    response = session.get(
        'http://push2.eastmoney.com/api/qt/stock/get',
        params={
            'secid': secid,
            'fields': 'f57,f58,f20,f21,f100',
            'ut': 'fa5fd1943c7b386f172d6893dbfba10b',
        },
        headers=STOCK_EASTMONEY_HEADERS,
        timeout=(5, 12),
        proxies={'http': None, 'https': None},
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get('data')
    if not data:
        raise ValueError('东方财富股票元数据为空')

    circ_market_cap = _safe_float(data.get('f21'))
    industry = str(data.get('f100', ''))

    return _with_industry_index_meta({
        'symbol': data.get('f57', symbol),
        'name': data.get('f58', ''),
        'totalMarketCap': _safe_float(data.get('f20')),
        'circMarketCap': circ_market_cap,
        'industry': industry,
        'capStyle': _cap_style_from_market_cap(circ_market_cap),
        'sectorIndexSymbol': _sector_index_symbol_from_industry(industry),
        'source': 'eastmoney',
    })


def fetch_stock_meta(target_type: str, symbol: str) -> dict:
    errors: list[str] = []
    if target_type == 'stock':
        for source_name, fn in [
            ('AKShare', lambda: fetch_stock_meta_from_akshare(symbol)),
            ('Tencent', lambda: fetch_stock_meta_from_tencent(symbol)),
            ('EastMoney', lambda: fetch_stock_meta_from_eastmoney(target_type, symbol)),
        ]:
            try:
                data = fn()
                if data.get('capStyle') or data.get('industry') or data.get('circMarketCap'):
                    return data
                errors.append(f'{source_name}: empty result')
            except Exception as exc:
                errors.append(f'{source_name}: {exc}')
        raise ValueError('; '.join(errors))
    return fetch_stock_meta_from_eastmoney(target_type, symbol)


def _safe_float_em(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def fetch_market_breadth_from_cfi() -> dict:
    session = requests.Session()
    session.trust_env = False
    response = session.post(
        CFI_MARKET_BREADTH_URL,
        headers={
            'User-Agent': STOCK_EASTMONEY_HEADERS.get('User-Agent', 'Mozilla/5.0'),
            'Referer': CFI_MARKET_BREADTH_REFERER,
            'Origin': 'https://gg.cfi.cn',
        },
        data={
            'search': '',
            'sortCol': '',
            'sortWay': '',
            'pageIndex': '1',
            'subvalue': '',
        },
        timeout=(5, 15),
        proxies={'http': None, 'https': None},
    )
    response.raise_for_status()
    text = response.text
    if 'A股涨跌家数统计' not in text:
        raise ValueError('CFI 未返回目标页面内容')

    pairs = re.findall(
        r'<td[^>]*>\s*(?:<font[^>]*>)?\s*([^<]+?)\s*(?:</font>)?\s*</td>\s*<td[^>]*>\s*(\d+)\s*</td>',
        text,
        flags=re.I,
    )
    if not pairs:
        raise ValueError('CFI 页面未解析到涨跌家数表格')

    stats = {name.strip(): int(value) for name, value in pairs}
    up_count = stats.get('上涨', 0)
    down_count = stats.get('下跌', 0)
    flat_count = stats.get('平盘', 0)
    limit_up_count = stats.get('涨停', 0)
    limit_down_count = stats.get('跌停', 0)
    total_count = up_count + down_count + flat_count

    return {
        'upCount': up_count,
        'downCount': down_count,
        'limitUpCount': limit_up_count,
        'limitDownCount': limit_down_count,
        'totalCount': total_count,
        'breakRate': None,
        'maxLianBan': None,
        'yesterdayLimitUpReturn': None,
        'totalTurnover': None,
        'downOver5Count': None,
        'new20HighCount': None,
        'new20LowCount': None,
        'source': 'cfi',
    }


def fetch_market_breadth_from_akshare() -> dict:
    if ak is None:
        raise ValueError('AKShare 不可用')

    def _load():
        return ak.stock_zh_a_spot_em()

    df = _without_proxy_env(_load)
    if df is None or df.empty:
        raise ValueError('AKShare A股实时行情为空')

    def col(name: str):
        return df[name] if name in df.columns else None

    chg = col('涨跌幅')
    turnover = col('成交额')

    if chg is None:
        raise ValueError('AKShare 实时行情缺少涨跌幅列')

    chg_series = chg.fillna(0).astype(float)
    up_count = int((chg_series > 0).sum())
    down_count = int((chg_series < 0).sum())
    limit_up_count = int((chg_series >= 9.5).sum())
    limit_down_count = int((chg_series <= -9.5).sum())
    down_over_5_count = int((chg_series <= -5).sum())

    new20_high_count = None
    new20_low_count = None
    total_turnover = float(turnover.fillna(0).astype(float).sum()) if turnover is not None else None

    return {
        'upCount': up_count,
        'downCount': down_count,
        'limitUpCount': limit_up_count,
        'limitDownCount': limit_down_count,
        'totalCount': int(len(df)),
        'breakRate': None,
        'maxLianBan': None,
        'yesterdayLimitUpReturn': None,
        'totalTurnover': total_turnover,
        'downOver5Count': down_over_5_count,
        'new20HighCount': new20_high_count,
        'new20LowCount': new20_low_count,
        'source': 'akshare',
    }


def fetch_market_breadth_from_eastmoney() -> dict:
    import time

    session = requests.Session()
    session.trust_env = False

    up_count = 0
    down_count = 0
    limit_up_count = 0
    limit_down_count = 0
    total_seen = 0

    page = 1
    max_pages = 70
    while page <= max_pages:
        try:
            response = session.get(
                'http://push2.eastmoney.com/api/qt/clist/get',
                params={
                    'pn': str(page),
                    'pz': '80',
                    'po': '1',
                    'np': '1',
                    'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
                    'fltt': '2',
                    'invt': '2',
                    'fid': 'f3',
                    'fs': 'm:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23',
                    'fields': 'f3,f12',
                },
                headers=STOCK_EASTMONEY_HEADERS,
                timeout=(5, 15),
                proxies={'http': None, 'https': None},
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get('data')
            if not data or not data.get('diff'):
                break

            rows = data['diff']
            for row in rows:
                chg = _safe_float_em(row.get('f3'))
                if chg > 0:
                    up_count += 1
                elif chg < 0:
                    down_count += 1
                if chg >= 9.5:
                    limit_up_count += 1
                elif chg <= -9.5:
                    limit_down_count += 1
                total_seen += 1

            if len(rows) < 80:
                break

            page += 1
            if page % 10 == 0:
                time.sleep(0.3)
        except Exception:
            break

    return {
        'upCount': up_count,
        'downCount': down_count,
        'limitUpCount': limit_up_count,
        'limitDownCount': limit_down_count,
        'totalCount': total_seen,
        'breakRate': None,
        'maxLianBan': None,
        'yesterdayLimitUpReturn': None,
        'totalTurnover': None,
        'downOver5Count': int(limit_down_count),
        'new20HighCount': None,
        'new20LowCount': None,
        'source': 'eastmoney',
    }


def fetch_market_breadth() -> dict:
    errors: list[str] = []
    for source_name, fn in [
        ('CFI', fetch_market_breadth_from_cfi),
        ('AKShare', fetch_market_breadth_from_akshare),
        ('EastMoney', fetch_market_breadth_from_eastmoney),
    ]:
        try:
            data = fn()
            if data.get('totalCount'):
                return data
            errors.append(f'{source_name}: empty result')
        except Exception as exc:
            errors.append(f'{source_name}: {exc}')
    raise ValueError('; '.join(errors))
