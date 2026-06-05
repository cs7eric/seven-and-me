from datetime import datetime
from pathlib import Path

from backend.config.settings import (
    REFERENCE_FOLDER,
    REFERENCE_INDEX_FILE,
    STOCK_REFERENCE_ANNOTATION_INDEX_FILE,
    STOCK_REFERENCE_CACHE_FOLDER,
    STOCK_REFERENCE_DATA_FOLDER,
    STOCK_REFERENCE_INDEX_FILE,
    STOCK_REFERENCE_WORKSPACE_INDEX_FILE,
)
from backend.repositories.reference_index import ensure_reference_index_files
from backend.utils.json_io import read_json_file, write_json_file


def stock_workspace_id(target_type: str, symbol: str) -> str:
    safe_target = (target_type or 'stock').strip().lower()
    safe_symbol = (symbol or '').strip().lower()
    return f'{safe_target}-{safe_symbol}'


def stock_annotation_file(target_type: str, symbol: str, period: str) -> Path:
    return STOCK_REFERENCE_DATA_FOLDER / 'annotations' / f'{stock_workspace_id(target_type, symbol)}-{period}.json'


def stock_workspace_file(target_type: str, symbol: str) -> Path:
    return STOCK_REFERENCE_DATA_FOLDER / 'snapshots' / f'{stock_workspace_id(target_type, symbol)}.json'


def stock_kline_cache_file(target_type: str, symbol: str, period: str, adjust: str) -> Path:
    return STOCK_REFERENCE_CACHE_FOLDER / 'klines' / f'{stock_workspace_id(target_type, symbol)}-{period}-{adjust}.json'


def stock_intraday_cache_file(target_type: str, symbol: str, trade_date: str) -> Path:
    safe_date = (trade_date or '').strip().replace('/', '-')
    return STOCK_REFERENCE_CACHE_FOLDER / 'intraday' / f'{stock_workspace_id(target_type, symbol)}-{safe_date}.json'


def load_stock_annotations(target_type: str, symbol: str, period: str) -> list[dict]:
    data = read_json_file(stock_annotation_file(target_type, symbol, period), {'items': []})
    return data.get('items', [])


def read_cached_stock_klines(target_type: str, symbol: str, period: str, adjust: str) -> list[dict]:
    cache_data = read_json_file(stock_kline_cache_file(target_type, symbol, period, adjust), {})
    items = cache_data.get('items') if isinstance(cache_data, dict) else None
    return items if isinstance(items, list) else []


def read_cached_stock_intraday(target_type: str, symbol: str, trade_date: str) -> dict | None:
    return read_json_file(stock_intraday_cache_file(target_type, symbol, trade_date), None)


def ensure_stock_workspace_entry(target_type: str, symbol: str, name: str) -> dict:
    ensure_reference_index_files()
    workspace_key = stock_workspace_id(target_type, symbol)
    index_payload = read_json_file(STOCK_REFERENCE_WORKSPACE_INDEX_FILE, {'items': []})
    items = index_payload.get('items', [])
    existing = next((item for item in items if item.get('id') == workspace_key), None)
    now = datetime.now().isoformat()
    data_file = str(stock_workspace_file(target_type, symbol).relative_to(REFERENCE_FOLDER)).replace('\\', '/')
    if existing:
        existing['name'] = name or existing.get('name') or symbol
        existing['updated_at'] = now
    else:
        items.insert(0, {
            'id': workspace_key,
            'target_type': target_type,
            'symbol': symbol,
            'name': name or symbol,
            'data_file': data_file,
            'created_at': now,
            'updated_at': now,
        })
    index_payload['items'] = items
    index_payload['updated_at'] = now
    write_json_file(STOCK_REFERENCE_WORKSPACE_INDEX_FILE, index_payload)
    return next(item for item in items if item.get('id') == workspace_key)


def load_stock_workspace(target_type: str, symbol: str) -> dict | None:
    data_file = str(stock_workspace_file(target_type, symbol))
    return read_json_file(Path(data_file), None)


def save_stock_workspace_entry(payload: dict) -> dict:
    target_type = payload.get('target_type', 'stock')
    symbol = payload.get('symbol', '')
    name = payload.get('name', symbol)
    ensure_stock_workspace_entry(target_type, symbol, name)
    now = datetime.now().isoformat()
    workspace_payload = {
        'target_type': target_type,
        'symbol': symbol,
        'name': name,
        'period': payload.get('period', '1d'),
        'adjust': payload.get('adjust', 'qfq'),
        'indicators': payload.get('indicators', []),
        'drawing_tool': payload.get('drawing_tool'),
        'show_auction_panel': payload.get('show_auction_panel', True),
        'updated_at': now,
    }
    write_json_file(stock_workspace_file(target_type, symbol), workspace_payload)

    root_index = read_json_file(REFERENCE_INDEX_FILE, {'types': {}})
    workspace_index = read_json_file(STOCK_REFERENCE_WORKSPACE_INDEX_FILE, {'items': []})
    items = workspace_index.get('items', [])
    root_index.setdefault('types', {})['stock_chart'] = {
        'title': 'Stock Chart Workspace',
        'index_file': str(STOCK_REFERENCE_INDEX_FILE.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
        'data_dir': str(STOCK_REFERENCE_DATA_FOLDER.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
        'count': len(items),
    }
    root_index['updated_at'] = now
    write_json_file(REFERENCE_INDEX_FILE, root_index)
    return workspace_payload
