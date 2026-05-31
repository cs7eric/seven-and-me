import requests

from backend.config.settings import STOCK_EASTMONEY_HEADERS, STOCK_EASTMONEY_SEARCH_URL


INDUSTRY_INDEX_QUERY_ALIASES = {
    '银行': ['中证银行', '国证银行', '银行指数', '银行'],
    '白酒': ['中证白酒', '白酒'],
    '酿酒': ['中证白酒', '白酒'],
    '食品饮料': ['食品饮料', '中证白酒', '白酒'],
    '半导体': ['半导体', '半导体行业精选'],
    '芯片': ['芯片', '半导体'],
    '电子': ['电子', '半导体'],
    '通信': ['通信', '中证TMT', '人工智能'],
    '人工智能': ['人工智能', 'AI'],
    'ai': ['人工智能', 'AI'],
    '软件': ['软件', '人工智能'],
    '计算机': ['计算机', '人工智能'],
    '医药': ['医药指数', '生物医药', '医药'],
    '生物': ['生物医药', '医药指数'],
    '医疗': ['医疗器械', '医药指数'],
    '新能源': ['新能源', '新能源车'],
    '电池': ['新能源电池', '新能源'],
    '光伏': ['光伏', '新能源'],
    '储能': ['储能', '新能源'],
    '风电': ['风电', '新能源'],
    '汽车': ['新能源汽车', '新能源车'],
    '汽车零部件': ['汽车零部件', '新能源车'],
    '军工': ['军工', '国防军工'],
    '机械': ['机械设备', '高端装备'],
    '环保': ['环保', '绿色电力'],
    '传媒': ['传媒', '文化传媒'],
    '文化传媒': ['文化传媒', '传媒'],
    '旅游': ['旅游', '酒店餐饮'],
    '酒店': ['酒店餐饮', '旅游'],
    '有色': ['有色金属', '有色'],
    '化工': ['化工', '新材料'],
    '煤炭': ['煤炭', '能源'],
    '房地产': ['房地产', '地产指数'],
    '地产': ['地产指数', '房地产'],
    '家用电器': ['家电', '家用电器'],
    '证券': ['券商指数', '证券'],
    '保险': ['保险', '金融'],
}


def eastmoney_search_to_target_type(item: dict) -> str | None:
    classify = str(item.get('Classify', '')).strip()
    security_type_name = str(item.get('SecurityTypeName', '')).strip()
    if classify == 'AStock' or security_type_name in {'深A', '沪A', '京A', '科创板', '创业板'}:
        return 'stock'
    if classify == 'Index' or '指数' in security_type_name:
        return 'index'
    if classify == 'Board':
        return 'sector'
    return None


def search_stock_chart(query: str) -> list[dict]:
    if not query:
        return []
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        STOCK_EASTMONEY_SEARCH_URL,
        params={
            'input': query,
            'type': '14',
            'token': 'D43BF722C8E33BDC906FB84D85E326E8',
            'count': '20',
        },
        headers=STOCK_EASTMONEY_HEADERS,
        timeout=(5, 12),
        proxies={'http': None, 'https': None},
    )
    response.raise_for_status()
    payload = response.json()
    data = (((payload.get('QuotationCodeTable') or {}).get('Data')) or [])
    items: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for raw in data:
        if not isinstance(raw, dict):
            continue
        target_type = eastmoney_search_to_target_type(raw)
        symbol = str(raw.get('Code', '')).strip()
        name = str(raw.get('Name', symbol)).strip() or symbol
        if not target_type or not symbol or not name:
            continue
        key = (target_type, symbol)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            'target_type': target_type,
            'symbol': symbol,
            'name': name,
        })
    return items


def infer_industry_search_queries(industry: str) -> list[str]:
    normalized = str(industry or '').strip().replace(' ', '')
    if not normalized:
        return []

    queries: list[str] = []
    for keyword, candidates in INDUSTRY_INDEX_QUERY_ALIASES.items():
        if keyword in normalized:
            for item in candidates:
                if item not in queries:
                    queries.append(item)
    if normalized not in queries:
        queries.append(normalized)
    return queries


def _index_candidate_score(item: dict, normalized: str, query: str) -> tuple[int, int, int, int, str]:
    name = str(item.get('name', '')).replace(' ', '')
    symbol = str(item.get('symbol', '')).strip()

    score = 0
    if normalized and normalized in name:
        score += 100
    if query and query.replace(' ', '') in name:
        score += 40
    if name.startswith('中证'):
        score += 30
    if name.startswith('国证'):
        score += 24
    if name.startswith('申万'):
        score += 20
    if '行业' in name:
        score += 10
    if '主题' in name:
        score += 6
    if 'A股' in name:
        score += 4
    if symbol.isdigit():
        score += 12
    if len(symbol) == 6 and symbol.isdigit():
        score += 6
    if name.startswith('恒生'):
        score -= 40
    if '香港' in name or '港股' in name:
        score -= 30
    if symbol.startswith('HS'):
        score -= 30

    exact_match = 1 if normalized and normalized == name else 0
    numeric_preferred = 1 if symbol.isdigit() else 0
    query_match = 1 if query and query.replace(' ', '') in name else 0
    return (-score, -exact_match, -numeric_preferred, -query_match, name)


def resolve_industry_index(industry: str) -> dict | None:
    normalized = str(industry or '').strip().replace(' ', '')
    if not normalized:
        return None

    queries = infer_industry_search_queries(normalized)
    for query in queries:
        try:
            items = search_stock_chart(query)
        except Exception:
            continue

        index_candidates = [item for item in items if item.get('target_type') == 'index']
        if not index_candidates:
            continue

        ranked = sorted(index_candidates, key=lambda item: _index_candidate_score(item, normalized, query))
        if ranked:
            chosen = ranked[0]
            return {
                'sectorIndexSymbol': str(chosen.get('symbol') or ''),
                'sectorIndexName': str(chosen.get('name') or ''),
                'industryQuery': query,
            }
    return None
