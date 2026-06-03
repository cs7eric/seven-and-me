from datetime import datetime

from flask import Blueprint, jsonify, request

from backend.adapters.market.eastmoney import fetch_stock_meta, fetch_market_breadth
from backend.config.settings import STOCK_REFERENCE_CACHE_FOLDER
from backend.repositories.stock.workspace_repo import stock_kline_cache_file
from backend.services.stock.auction_service import fetch_stock_auction
from backend.services.stock.kline_service import resolve_stock_klines
from backend.services.stock.application_analysis_service import run_application_analysis
from backend.services.stock.application_analysis_scheduler import (
    get_application_analysis_scheduler_status,
    list_application_analysis_results,
    list_application_analysis_targets,
    list_recent30_snapshots,
    list_recent30_snapshots_full,
    read_recent30_snapshot,
    run_recent30_for_target,
    start_application_analysis_scheduler,
    stop_application_analysis_scheduler,
    trigger_application_analysis,
)
from backend.services.stock.application_analysis_store import load_targets, result_path, save_targets, list_history, read_result
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


@stock_chart_bp.route('/api/stock-chart/application-analysis/targets', methods=['GET'])
def list_application_analysis_targets_api():
    return jsonify({'items': list_application_analysis_targets(), 'config': load_targets()})


@stock_chart_bp.route('/api/stock-chart/application-analysis/targets', methods=['PUT'])
def save_application_analysis_targets_api():
    payload = request.get_json() or {}
    saved = save_targets(payload)
    return jsonify({'ok': True, 'config': saved})


@stock_chart_bp.route('/api/stock-chart/application-analysis/results', methods=['GET'])
def list_application_analysis_results_api():
    return jsonify({'items': list_application_analysis_results()})


@stock_chart_bp.route('/api/stock-chart/application-analysis/results/<target_id>', methods=['GET'])
def get_application_analysis_result_api(target_id: str):
    config = load_targets()
    target = next((item for item in config.get('items', []) if item.get('id') == target_id), None)
    if not target:
        return jsonify({'error': f'target {target_id} not found'}), 404
    result = read_result(target)
    if not result:
        return jsonify({'error': f'no result for {target_id}', 'path': str(result_path(target))}), 404
    result['_meta_result_path'] = str(result_path(target))
    history = list_history(target, limit=20)
    result['_meta_history'] = history
    return jsonify(result)


@stock_chart_bp.route('/api/stock-chart/application-analysis/refresh', methods=['POST'])
def refresh_application_analysis_api():
    payload = request.get_json() or {}
    target_id = payload.get('target_id') or request.args.get('target_id')
    result = trigger_application_analysis(target_id, source='api')
    return jsonify(result)


@stock_chart_bp.route('/api/stock-chart/application-analysis/scheduler', methods=['GET'])
def application_analysis_scheduler_status_api():
    return jsonify(get_application_analysis_scheduler_status())


@stock_chart_bp.route('/api/stock-chart/application-analysis/scheduler/start', methods=['POST'])
def application_analysis_scheduler_start_api():
    start_application_analysis_scheduler()
    return jsonify({'ok': True, 'status': get_application_analysis_scheduler_status()})


@stock_chart_bp.route('/api/stock-chart/application-analysis/scheduler/stop', methods=['POST'])
def application_analysis_scheduler_stop_api():
    stop_application_analysis_scheduler()
    return jsonify({'ok': True, 'status': get_application_analysis_scheduler_status()})


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


@stock_chart_bp.route('/api/stock-chart/application-analysis', methods=['POST'])
def stock_chart_application_analysis():
    data = request.get_json() or {}
    target_type = str(data.get('target_type', 'stock')).strip() or 'stock'
    symbol = str(data.get('symbol', '000001')).strip() or '000001'
    name = str(data.get('name', symbol)).strip() or symbol
    adjust = str(data.get('adjust', 'qfq')).strip() or 'qfq'
    try:
        return jsonify(run_application_analysis(target_type, symbol, name, adjust))
    except Exception as exc:
        return jsonify({'error': str(exc)}), 502


@stock_chart_bp.route('/api/stock-chart/application-analysis/recent30/refresh', methods=['POST'])
def refresh_recent30_application_analysis_api():
    data = request.get_json() or {}
    target_id = str(data.get('target_id') or '').strip()
    if not target_id:
        return jsonify({'ok': False, 'error': 'target_id required'}), 400
    date_key = data.get('date')
    if isinstance(date_key, str) and date_key.strip():
        date_key = date_key.strip()
    else:
        date_key = None
    return jsonify(run_recent30_for_target(target_id, source='api_recent30', date_key=date_key))


@stock_chart_bp.route('/api/stock-chart/application-analysis/recent30/<target_id>', methods=['GET'])
def list_recent30_application_analysis_api(target_id: str):
    try:
        limit = int(request.args.get('limit') or 60)
    except (TypeError, ValueError):
        limit = 60
    return jsonify(list_recent30_snapshots(target_id, limit=max(1, min(limit, 200))))


@stock_chart_bp.route('/api/stock-chart/application-analysis/recent30/<target_id>/full', methods=['GET'])
def list_recent30_application_analysis_full_api(target_id: str):
    """
    批量返回所有快照的完整内容（直接从 JSON 读取）。
    服务默认从此处读取 AI Direction 数据，前端不再依赖实时 analysis。
    """
    try:
        limit = int(request.args.get('limit') or 60)
    except (TypeError, ValueError):
        limit = 60
    return jsonify(list_recent30_snapshots_full(target_id, limit=max(1, min(limit, 200))))


@stock_chart_bp.route('/api/stock-chart/application-analysis/recent30/<target_id>/<date_key>', methods=['GET'])
def read_recent30_application_analysis_api(target_id: str, date_key: str):
    return jsonify(read_recent30_snapshot(target_id, date_key))


@stock_chart_bp.route('/api/stock-chart/market-overview')
def stock_chart_market_overview():
    try:
        return jsonify(build_market_overview())
    except Exception as exc:
        return jsonify({'error': str(exc)}), 502
