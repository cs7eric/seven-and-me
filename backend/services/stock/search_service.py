import requests

from backend.config.settings import STOCK_EASTMONEY_HEADERS, STOCK_EASTMONEY_SEARCH_URL


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
