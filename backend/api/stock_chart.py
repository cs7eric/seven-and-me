from datetime import datetime

from flask import Blueprint, jsonify, request

from backend.adapters.market.eastmoney import fetch_stock_meta, fetch_market_breadth
from backend.config.settings import STOCK_REFERENCE_CACHE_FOLDER
from backend.repositories.stock.workspace_repo import stock_kline_cache_file
from backend.services.stock.auction_service import fetch_stock_auction
from backend.services.stock.kline_service import resolve_stock_klines
from backend.services.stock.market_overview_service import build_market_overview
from backend.services.stock.search_service import search_stock_chart
from backend.services.stock.workspace_service import (
    create_stock_annotation,
    get_stock_workspace,
    list_stock_annotations,
    put_stock_workspace,
    remove_stock_annotation,
    update_stock_annotation,
)
from backend.utils.json_io import read_json_file, write_json_file

stock_chart_bp = Blueprint('stock_chart', __name__)


def sample_stock_klines(symbol: str, period: str) -> list[dict]:
    from backend.services.stock.sample_data_service import sample_stock_klines as app_sample_stock_klines
    return app_sample_stock_klines(symbol, period)


@stock_chart_bp.route('/api/stock-chart/search')
def stock_chart_search():
    query = str(request.args.get('q', '')).strip()
    try:
        return jsonify({'items': search_stock_chart(query)})
    except Exception as exc:
        return jsonify({'items': [], 'error': str(exc)}), 502


@stock_chart_bp.route('/api/stock-chart/klines')
def stock_chart_klines():
    target_type = str(request.args.get('target_type', 'stock')).strip() or 'stock'
    symbol = str(request.args.get('symbol', '000001')).strip() or '000001'
    name = str(request.args.get('name', symbol)).strip() or symbol
    period = str(request.args.get('period', '1d')).strip() or '1d'
    adjust = str(request.args.get('adjust', 'qfq')).strip() or 'qfq'
    items, source = resolve_stock_klines(target_type, symbol, period, adjust, sample_stock_klines)
    cache_file = stock_kline_cache_file(target_type, symbol, period, adjust)
    payload = {
        'symbol': symbol,
        'target_type': target_type,
        'period': period,
        'adjust': adjust,
        'updated_at': datetime.now().isoformat(),
        'source': source,
        'items': items,
    }
    write_json_file(cache_file, payload)
    return jsonify(payload)


@stock_chart_bp.route('/api/stock-chart/workspace')
def stock_chart_workspace():
    target_type = str(request.args.get('target_type', 'stock')).strip() or 'stock'
    symbol = str(request.args.get('symbol', '000001')).strip() or '000001'
    name = str(request.args.get('name', symbol)).strip() or symbol
    return jsonify(get_stock_workspace(target_type, symbol, name))


@stock_chart_bp.route('/api/stock-chart/workspace', methods=['PUT'])
def save_stock_chart_workspace():
    data = request.get_json() or {}
    return jsonify(put_stock_workspace(data))


@stock_chart_bp.route('/api/stock-chart/annotations')
def stock_chart_annotations():
    target_type = str(request.args.get('target_type', 'stock')).strip() or 'stock'
    symbol = str(request.args.get('symbol', '000001')).strip() or '000001'
    period = str(request.args.get('period', '1d')).strip() or '1d'
    return jsonify({'items': list_stock_annotations(target_type, symbol, period)})


@stock_chart_bp.route('/api/stock-chart/annotations', methods=['POST'])
def create_stock_chart_annotation():
    data = request.get_json() or {}
    return jsonify(create_stock_annotation(data))


@stock_chart_bp.route('/api/stock-chart/annotations/<annotation_id>', methods=['PUT'])
def update_stock_chart_annotation(annotation_id):
    data = request.get_json() or {}
    item = update_stock_annotation(annotation_id, data)
    if item:
        return jsonify(item)
    return jsonify({'error': 'Annotation not found'}), 404


@stock_chart_bp.route('/api/stock-chart/annotations/<annotation_id>', methods=['DELETE'])
def delete_stock_chart_annotation(annotation_id):
    target_type = str(request.args.get('target_type', 'stock')).strip() or 'stock'
    symbol = str(request.args.get('symbol', '000001')).strip() or '000001'
    period = str(request.args.get('period', '1d')).strip() or '1d'
    ok = remove_stock_annotation(target_type, symbol, period, annotation_id)
    return jsonify({'ok': ok})


@stock_chart_bp.route('/api/stock-chart/auction')
def stock_chart_auction():
    symbol = str(request.args.get('symbol', '000001')).strip() or '000001'
    return jsonify(fetch_stock_auction(symbol))


@stock_chart_bp.route('/api/stock-chart/stock-meta')
def stock_chart_meta():
    target_type = str(request.args.get('target_type', 'stock')).strip() or 'stock'
    symbol = str(request.args.get('symbol', '000001')).strip() or '000001'
    try:
        return jsonify(fetch_stock_meta(target_type, symbol))
    except Exception as exc:
        return jsonify({'error': str(exc), 'symbol': symbol, 'capStyle': None, 'sectorIndexSymbol': None, 'sectorIndexName': None}), 200


_BREADTH_CACHE_FILE = STOCK_REFERENCE_CACHE_FOLDER / 'breadth' / 'latest.json'
_BREADTH_SERIES_CACHE_FILE = STOCK_REFERENCE_CACHE_FOLDER / 'breadth' / 'series.json'
_BREADTH_CACHE_TTL_SEC = 60
_MAX_SERIES_DAYS = 500


@stock_chart_bp.route('/api/stock-chart/market-breadth')
def stock_chart_breadth():
    now_ts = datetime.now().timestamp()
    cached = read_json_file(_BREADTH_CACHE_FILE, None)
    if cached and isinstance(cached, dict) and cached.get('cachedAt'):
        age = now_ts - cached['cachedAt']
        if age < _BREADTH_CACHE_TTL_SEC:
            return jsonify(cached)

    try:
        raw = fetch_market_breadth()
        payload = {
            'upCount': raw.get('upCount', 0),
            'downCount': raw.get('downCount', 0),
            'limitUpCount': raw.get('limitUpCount', 0),
            'limitDownCount': raw.get('limitDownCount', 0),
            'totalCount': raw.get('totalCount', 0),
            'breakRate': raw.get('breakRate'),
            'maxLianBan': raw.get('maxLianBan'),
            'yesterdayLimitUpReturn': raw.get('yesterdayLimitUpReturn'),
            'totalTurnover': raw.get('totalTurnover'),
            'downOver5Count': raw.get('downOver5Count'),
            'new20HighCount': raw.get('new20HighCount'),
            'new20LowCount': raw.get('new20LowCount'),
            'source': raw.get('source'),
            'cachedAt': now_ts,
            'date': datetime.now().strftime('%Y-%m-%d'),
        }

        series = read_json_file(_BREADTH_SERIES_CACHE_FILE, [])
        if not isinstance(series, list):
            series = []
        replaced = False
        for i, item in enumerate(series):
            if isinstance(item, dict) and item.get('date') == payload['date']:
                series[i] = payload
                replaced = True
                break
        if not replaced:
            series.append(payload)
        series.sort(key=lambda x: str(x.get('date', '')))
        series = series[-_MAX_SERIES_DAYS:]
        _BREADTH_SERIES_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        write_json_file(_BREADTH_SERIES_CACHE_FILE, series)

        _BREADTH_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        write_json_file(_BREADTH_CACHE_FILE, payload)
        return jsonify(payload)
    except Exception as exc:
        if cached:
            return jsonify(cached)
        return jsonify({'error': str(exc), 'cachedAt': None}), 502


@stock_chart_bp.route('/api/stock-chart/market-breadth-series')
def stock_chart_breadth_series():
    series = read_json_file(_BREADTH_SERIES_CACHE_FILE, [])
    if not series:
        return jsonify({'items': []})
    return jsonify({'items': series})


@stock_chart_bp.route('/api/stock-chart/market-overview')
def stock_chart_market_overview():
    try:
        return jsonify(build_market_overview())
    except Exception as exc:
        return jsonify({'error': str(exc)}), 502
