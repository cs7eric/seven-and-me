from datetime import datetime

from backend.config.settings import STOCK_REFERENCE_ANNOTATION_INDEX_FILE
from backend.utils.json_io import read_json_file, write_json_file
from backend.repositories.stock.workspace_repo import stock_annotation_file, stock_workspace_id


def save_stock_annotation(payload: dict) -> dict:
    target_type = payload.get('target_type', 'stock')
    symbol = payload.get('symbol', '')
    period = payload.get('period', '1d')
    items = read_json_file(stock_annotation_file(target_type, symbol, period), {'items': []}).get('items', [])
    now = datetime.now().isoformat()
    item = {
        'id': payload.get('id') or f'anno-{int(datetime.now().timestamp() * 1000)}',
        'target_type': target_type,
        'symbol': symbol,
        'period': period,
        'title': payload.get('title', ''),
        'content': payload.get('content', ''),
        'bar_time': payload.get('bar_time'),
        'x': payload.get('x'),
        'y': payload.get('y'),
        'color': payload.get('color', '#ef4444'),
        'created_at': payload.get('created_at') or now,
        'updated_at': now,
    }
    items = [existing for existing in items if existing.get('id') != item['id']]
    items.insert(0, item)
    write_json_file(stock_annotation_file(target_type, symbol, period), {'items': items})

    index_payload = read_json_file(STOCK_REFERENCE_ANNOTATION_INDEX_FILE, {'items': []})
    index_items = [existing for existing in index_payload.get('items', []) if existing.get('id') != item['id']]
    index_items.insert(0, {
        'id': item['id'],
        'workspace_id': stock_workspace_id(target_type, symbol),
        'target_type': target_type,
        'symbol': symbol,
        'period': period,
        'title': item['title'],
        'updated_at': now,
    })
    index_payload['items'] = index_items
    index_payload['updated_at'] = now
    write_json_file(STOCK_REFERENCE_ANNOTATION_INDEX_FILE, index_payload)
    return item


def delete_stock_annotation(target_type: str, symbol: str, period: str, annotation_id: str) -> bool:
    payload = read_json_file(stock_annotation_file(target_type, symbol, period), {'items': []})
    items = payload.get('items', [])
    filtered = [item for item in items if item.get('id') != annotation_id]
    if len(filtered) == len(items):
        return False
    write_json_file(stock_annotation_file(target_type, symbol, period), {'items': filtered})

    index_payload = read_json_file(STOCK_REFERENCE_ANNOTATION_INDEX_FILE, {'items': []})
    index_payload['items'] = [item for item in index_payload.get('items', []) if item.get('id') != annotation_id]
    index_payload['updated_at'] = datetime.now().isoformat()
    write_json_file(STOCK_REFERENCE_ANNOTATION_INDEX_FILE, index_payload)
    return True
