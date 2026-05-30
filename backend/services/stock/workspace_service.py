from datetime import datetime
import time

from backend.repositories.stock.annotation_repo import delete_stock_annotation, save_stock_annotation
from backend.repositories.stock.workspace_repo import (
    ensure_stock_workspace_entry,
    load_stock_annotations,
    stock_annotation_file,
    stock_workspace_file,
)
from backend.utils.json_io import read_json_file, write_json_file


def get_stock_workspace(target_type: str, symbol: str, name: str) -> dict:
    entry = ensure_stock_workspace_entry(target_type, symbol, name)
    workspace_file = stock_workspace_file(target_type, symbol)
    workspace = read_json_file(workspace_file, {
        'id': entry['id'],
        'symbol': symbol,
        'target_type': target_type,
        'period': '1d',
        'adjust': 'qfq',
        'indicators': ['MA', 'EMA', 'BOLL', 'MACD', 'VOL', 'AMOUNT', 'VOLUME_RATIO'],
        'drawing_tool': None,
        'show_auction_panel': True,
        'updated_at': None,
    })
    write_json_file(workspace_file, workspace)
    return workspace


def put_stock_workspace(data: dict) -> dict:
    target_type = str(data.get('target_type', 'stock')).strip() or 'stock'
    symbol = str(data.get('symbol', '000001')).strip() or '000001'
    name = str(data.get('name', symbol)).strip() or symbol
    entry = ensure_stock_workspace_entry(target_type, symbol, name)
    payload = {
        'id': entry['id'],
        'symbol': symbol,
        'target_type': target_type,
        'period': str(data.get('period', '1d')),
        'adjust': str(data.get('adjust', 'qfq')),
        'indicators': data.get('indicators') or [],
        'drawing_tool': data.get('drawing_tool'),
        'show_auction_panel': bool(data.get('show_auction_panel', True)),
        'updated_at': datetime.now().isoformat(),
    }
    write_json_file(stock_workspace_file(target_type, symbol), payload)
    return payload


def list_stock_annotations(target_type: str, symbol: str, period: str) -> list[dict]:
    return load_stock_annotations(target_type, symbol, period)


def create_stock_annotation(data: dict) -> dict:
    target_type = str(data.get('target_type', 'stock')).strip() or 'stock'
    symbol = str(data.get('symbol', '000001')).strip() or '000001'
    period = str(data.get('period', '1d')).strip() or '1d'
    annotation_file = stock_annotation_file(target_type, symbol, period)
    annotation_data = read_json_file(annotation_file, {'items': []})
    item = {
        'id': data.get('id') or f'anno-{int(time.time() * 1000)}',
        'overlay_type': data.get('overlay_type') or 'segment',
        'points': data.get('points') or [],
        'styles': data.get('styles') or {},
        'text': data.get('text') or '',
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat(),
    }
    annotation_data.setdefault('items', []).insert(0, item)
    write_json_file(annotation_file, annotation_data)
    return item


def update_stock_annotation(annotation_id: str, data: dict) -> dict | None:
    target_type = str(data.get('target_type', 'stock')).strip() or 'stock'
    symbol = str(data.get('symbol', '000001')).strip() or '000001'
    period = str(data.get('period', '1d')).strip() or '1d'
    annotation_file = stock_annotation_file(target_type, symbol, period)
    annotation_data = read_json_file(annotation_file, {'items': []})
    for item in annotation_data.get('items', []):
        if item.get('id') == annotation_id:
            item['points'] = data.get('points') or item.get('points') or []
            item['styles'] = data.get('styles') or item.get('styles') or {}
            item['text'] = data.get('text', item.get('text', ''))
            item['updated_at'] = datetime.now().isoformat()
            write_json_file(annotation_file, annotation_data)
            return item
    return None


def remove_stock_annotation(target_type: str, symbol: str, period: str, annotation_id: str) -> bool:
    return delete_stock_annotation(target_type, symbol, period, annotation_id)
