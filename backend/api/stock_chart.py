from datetime import datetime, timedelta
from typing import Any

from flask import Blueprint, jsonify, request


# ---------------------------------------------------------------------------
# 北京时间 (UTC+8) 辅助, 给 ths_industry_constituents_file 用
# ---------------------------------------------------------------------------
def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _beijing_today():
    return _beijing_now().date()

from backend.adapters.market.eastmoney import fetch_stock_meta, fetch_market_breadth
from backend.config.settings import STOCK_REFERENCE_CACHE_FOLDER
from backend.repositories.stock.workspace_repo import stock_kline_cache_file
from backend.services.stock.turnover_repo import load_turnover
from backend.services.stock.auction_service import fetch_stock_auction
from backend.services.scheduler.auction_analysis_scheduler import (
    get_auction_analysis_scheduler,
    get_auction_analysis_scheduler_status,
)
from backend.services.stock.auction_ai_analysis_service import (
    list_auction_analysis_snapshots,
    read_auction_analysis_snapshot,
    run_auction_ai_analysis_target,
)
from backend.services.stock.kline_service import build_intraday_snapshot, resolve_stock_klines
from backend.services.stock.etf_poc_service import build_etf_poc
from backend.services.stock.application_analysis_service import run_application_analysis
from backend.services.stock.feature_summary import build_stock_feature_summary
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
from backend.services.stock.market_heatmap_service import build_market_heatmap
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

def _merge_turnover_into_kline_items(target_type: str, symbol: str, items: list[dict]) -> list[dict]:
    payload = load_turnover(target_type, symbol)
    if not payload:
        return items
    entries = payload.get('entries') if isinstance(payload, dict) else None
    if not isinstance(entries, list) or not entries:
        return items

    by_timestamp: dict[int, dict] = {}
    by_trade_date: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ts = entry.get('timestamp')
        td = entry.get('trade_date')
        if isinstance(ts, (int, float)):
            by_timestamp[int(ts)] = entry
        if isinstance(td, str) and td.strip():
            by_trade_date[td.strip()] = entry

    merged: list[dict] = []
    for bar in items:
        row = dict(bar)
        ts = row.get('timestamp')
        match = by_timestamp.get(int(ts)) if isinstance(ts, (int, float)) else None
        if match is None:
            trade_date = str(row.get('trade_date') or row.get('date') or '').strip()
            if trade_date:
                match = by_trade_date.get(trade_date)
        if match:
            row['turnover_rate'] = match.get('turnover_rate')
            if not row.get('trade_date') and match.get('trade_date'):
                row['trade_date'] = match.get('trade_date')
            if not row.get('turnover') and isinstance(match.get('amount'), (int, float)):
                row['turnover'] = match.get('amount')
        merged.append(row)
    return merged



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
    items = _merge_turnover_into_kline_items(target_type, symbol, items)
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


@stock_chart_bp.route('/api/stock-chart/etf/poc')
def stock_chart_etf_poc():
    symbol = str(request.args.get('symbol', '510300')).strip() or '510300'
    period = str(request.args.get('period', '1d')).strip() or '1d'
    adjust = str(request.args.get('adjust', 'qfq')).strip() or 'qfq'
    try:
        kline_count = int(request.args.get('count') or 120)
    except (TypeError, ValueError):
        kline_count = 120
    try:
        holdings_limit = int(request.args.get('holdings_limit') or 20)
    except (TypeError, ValueError):
        holdings_limit = 20

    try:
        return jsonify(build_etf_poc(
            symbol,
            period=period,
            adjust=adjust,
            kline_count=max(1, min(kline_count, 500)),
            holdings_limit=max(1, min(holdings_limit, 100)),
        ))
    except Exception as exc:
        return jsonify({
            'ok': False,
            'target_type': 'etf',
            'symbol': symbol,
            'error': str(exc),
        }), 502


@stock_chart_bp.route('/api/stock-chart/intraday')
def stock_chart_intraday():
    target_type = str(request.args.get('target_type', 'stock')).strip() or 'stock'
    symbol = str(request.args.get('symbol', '000001')).strip() or '000001'
    name = str(request.args.get('name', symbol)).strip() or symbol
    adjust = str(request.args.get('adjust', 'qfq')).strip() or 'qfq'
    trade_date = str(request.args.get('trade_date', '')).strip() or None
    raw_periods = str(request.args.get('periods', '')).strip()
    periods: list[str] = []
    for token in raw_periods.split(','):
        value = token.strip()
        if not value:
            continue
        if value not in {'1m', '5m', '15m', '30m', '60m', '120m'}:
            continue
        if value not in periods:
            periods.append(value)
    if not periods:
        periods = ['1m', '5m', '15m', '30m']
    try:
        snapshot, source = build_intraday_snapshot(
            target_type,
            symbol,
            adjust,
            sample_stock_klines,
            trade_date=trade_date,
            periods=periods,
        )
        return jsonify({
            'ok': True,
            'symbol': symbol,
            'target_type': target_type,
            'name': name,
            'adjust': adjust,
            'source': source,
            'requested_periods': periods,
            **snapshot,
        })
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc), 'symbol': symbol, 'target_type': target_type, 'requested_periods': periods}), 502


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


@stock_chart_bp.route('/api/stock-chart/feature-summary')
def stock_chart_feature_summary():
    target_type = str(request.args.get('target_type', 'stock')).strip() or 'stock'
    symbol = str(request.args.get('symbol', '000001')).strip() or '000001'
    name = str(request.args.get('name', symbol)).strip() or symbol
    adjust = str(request.args.get('adjust', 'qfq')).strip() or 'qfq'
    try:
        max_chars = int(request.args.get('max_chars') or 1000000)
    except (TypeError, ValueError):
        max_chars = 1000000
    try:
        return jsonify(build_stock_feature_summary(
            target_type=target_type,
            symbol=symbol,
            name=name,
            adjust=adjust,
            max_chars=max_chars,
        ))
    except Exception as exc:
        return jsonify({'error': str(exc)}), 502


@stock_chart_bp.route('/api/stock-chart/auction-ai-analysis', methods=['POST'])
def stock_chart_auction_ai_analysis():
    data = request.get_json(silent=True) or {}
    target_type = str(data.get('target_type') or request.args.get('target_type') or 'stock').strip() or 'stock'
    symbol = str(data.get('symbol') or request.args.get('symbol') or '000001').strip() or '000001'
    name = str(data.get('name') or request.args.get('name') or symbol).strip() or symbol
    adjust = str(data.get('adjust') or request.args.get('adjust') or 'qfq').strip() or 'qfq'
    try:
        max_chars = int(data.get('max_chars') or request.args.get('max_chars') or 1000000)
    except (TypeError, ValueError):
        max_chars = 1000000
    try:
        # max_chars is kept for API compatibility; the persisted scheduler path uses
        # the configured service budget.
        _ = max_chars
        return jsonify(run_auction_ai_analysis_target({
            'id': f'{target_type}-{symbol}',
            'target_type': target_type,
            'symbol': symbol,
            'name': name,
            'adjust': adjust,
            'enabled': True,
        }))
    except Exception as exc:
        return jsonify({'error': str(exc)}), 502


@stock_chart_bp.route('/api/stock-chart/auction-ai-analysis', methods=['GET'])
def read_stock_chart_auction_ai_analysis():
    target_type = str(request.args.get('target_type', 'stock')).strip() or 'stock'
    symbol = str(request.args.get('symbol', '000001')).strip() or '000001'
    date_key = request.args.get('date') or None
    snapshot = read_auction_analysis_snapshot(target_type, symbol, date_key)
    if not snapshot:
        return jsonify({
            'ok': False,
            'has_snapshot': False,
            'target_type': target_type,
            'symbol': symbol,
            'date': date_key,
            'error': '今日暂无持久化竞价 AI 分析结果',
        }), 404
    return jsonify({'ok': True, 'has_snapshot': True, **snapshot})


@stock_chart_bp.route('/api/stock-chart/auction-ai-analysis/history', methods=['GET'])
def list_stock_chart_auction_ai_analysis_history():
    target_type = str(request.args.get('target_type', 'stock')).strip() or 'stock'
    symbol = str(request.args.get('symbol', '000001')).strip() or '000001'
    try:
        limit = int(request.args.get('limit') or 30)
    except (TypeError, ValueError):
        limit = 30
    return jsonify({
        'ok': True,
        'target_type': target_type,
        'symbol': symbol,
        'items': list_auction_analysis_snapshots(target_type, symbol, limit=limit),
    })


@stock_chart_bp.route('/api/stock-chart/auction-ai-analysis/scheduler', methods=['GET'])
def stock_chart_auction_ai_analysis_scheduler_status():
    return jsonify(get_auction_analysis_scheduler_status())


@stock_chart_bp.route('/api/stock-chart/auction-ai-analysis/scheduler/trigger', methods=['POST'])
def stock_chart_auction_ai_analysis_scheduler_trigger():
    return jsonify(get_auction_analysis_scheduler().trigger_now())


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


# ============================================================================
# 大盘成交额 / 主力净流入 (AKShare 双源, 独立于上面 K线技术分析的 market_overview)
# 路径前缀用 /market-overview-akshare/ 避免跟上面的 /market-overview/ 冲突.
# 数据由 backend/services/stock/market_overview_akshare_service.py + scheduler 维护.
# ============================================================================
@stock_chart_bp.route('/api/stock-chart/market-overview-akshare')
def stock_chart_market_overview_akshare():
    """读 latest akshare snapshot (成交额 / 主力净流入 / 涨跌家数)."""
    from backend.services.stock.market_overview_akshare_service import get_latest_snapshot
    try:
        return jsonify(get_latest_snapshot())
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@stock_chart_bp.route('/api/stock-chart/market-overview-akshare/refresh', methods=['POST'])
def stock_chart_market_overview_akshare_refresh():
    """手动触发一次 AKShare 拉取 + 落盘 (调试 / 立刻拉最新用)."""
    from backend.services.scheduler.market_overview_scheduler import (
        run_market_overview_snapshot_now,
    )
    try:
        snap = run_market_overview_snapshot_now(force=True)
        if snap is None:
            return jsonify({"ok": False, "error": "akshare unavailable or empty"}), 502
        return jsonify({"ok": True, "snapshot": snap})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@stock_chart_bp.route('/api/stock-chart/market-overview-akshare/scheduler/status')
def stock_chart_market_overview_akshare_scheduler_status():
    from backend.services.scheduler.market_overview_scheduler import (
        get_market_overview_scheduler_status,
    )
    return jsonify(get_market_overview_scheduler_status())


@stock_chart_bp.route('/api/stock-chart/market-overview-akshare/archive/<string:trading_date>')
def stock_chart_market_overview_akshare_archive(trading_date: str):
    """按交易日 (YYYY-MM-DD 或 YYYYMMDD) 读历史 snapshot."""
    from backend.services.stock.market_overview_akshare_service import get_archived_snapshot
    snap = get_archived_snapshot(trading_date)
    if snap is None:
        return jsonify({"ok": False, "error": f"archive {trading_date} not found"}), 404
    return jsonify(snap)


# =============================================================================
# 行业 / 概念 应用面分析（独立于 application-analysis）
# 数据源：eltdx bars.get(kind="index")
# 持久化：reference/industry-application/  (独立)
# =============================================================================

try:
    from backend.services.stock import industry_application_service as ia_service
    from backend.services.stock.industry_application_store import load_targets as ia_load_targets
    from backend.services.stock.industry_application_store import save_targets as ia_save_targets
except ImportError:  # 允许模块缺失时仍启动
    ia_service = None  # type: ignore[assignment]


@stock_chart_bp.route('/api/stock-chart/industry-application/targets', methods=['GET'])
def industry_application_list_targets():
    """行业 / 概念 应用面分析 targets 列表。"""
    if ia_service is None:
        return jsonify({'error': 'industry_application_service 未安装'}), 501
    return jsonify(ia_service.fetch_targets())


@stock_chart_bp.route('/api/stock-chart/industry-application/targets', methods=['PUT'])
def industry_application_save_targets():
    """保存 targets。"""
    if ia_service is None:
        return jsonify({'error': 'industry_application_service 未安装'}), 501
    payload = request.get_json(silent=True) or {}
    return jsonify(ia_service.upsert_targets(payload))


@stock_chart_bp.route('/api/stock-chart/industry-application/target-codes')
def industry_application_target_codes():
    """返回所有可加进 targets 的 行业 / 概念 代码（来自 index_codes.py）。

    ``kind`` 可选: ``industry`` / ``concept`` / 留空返回全部。
    """
    if ia_service is None:
        return jsonify({'error': 'industry_application_service 未安装'}), 501
    kind = str(request.args.get('kind', '')).strip().lower()
    items = ia_service.collect_all_target_codes()
    if kind in {'industry', 'concept'}:
        items = [it for it in items if it.get('kind') == kind]
    return jsonify({'items': items, 'count': len(items), 'source': 'index_codes.py'})


@stock_chart_bp.route('/api/stock-chart/industry-application/kline')
def industry_application_kline():
    """拉取某个行业 / 概念 指数的 K 线 + 技术指标（不落盘）。"""
    if ia_service is None:
        return jsonify({'error': 'industry_application_service 未安装'}), 501
    target_type = str(request.args.get('target_type', '')).strip().lower() or 'industry'
    symbol = str(request.args.get('symbol', '')).strip().lower()
    period = str(request.args.get('period', 'day')).strip() or 'day'
    try:
        count = int(request.args.get('count', 120))
    except (TypeError, ValueError):
        count = 120
    if not symbol:
        return jsonify({'error': 'symbol 不能为空'}), 400
    try:
        return jsonify(ia_service.fetch_kline(target_type, symbol, period=period, count=count))
    except ValueError as exc:
        return jsonify({'error': str(exc), 'error_type': 'bad_request'}), 400
    except Exception as exc:
        return jsonify({'error': str(exc), 'error_type': 'upstream_failure'}), 502


@stock_chart_bp.route('/api/stock-chart/industry-application/refresh', methods=['POST'])
def industry_application_refresh():
    """触发一次拉取 + 落盘 (targets.json 里所有 enabled 标的)。"""
    if ia_service is None:
        return jsonify({'error': 'industry_application_service 未安装'}), 501
    payload = request.get_json(silent=True) or {}
    only_id = payload.get('target_id')

    targets = ia_service.fetch_targets()
    items = [
        it for it in targets.get('items', [])
        if it.get('enabled', True) and (not only_id or it.get('id') == only_id)
    ]
    if not items:
        return jsonify({'ok': False, 'error': '没有 enabled 标的', 'count': 0}), 200

    results: list[dict[str, Any]] = []
    for item in items:
        try:
            r = ia_service.refresh_target(item)
            results.append({'id': item.get('id'), 'ok': True, 'kline_count': r.get('kline_count')})
        except Exception as exc:  # noqa: BLE001
            results.append({'id': item.get('id'), 'ok': False, 'error': str(exc)})
    ok = all(r.get('ok') for r in results)
    return jsonify({'ok': ok, 'items': results, 'count': len(results)})


@stock_chart_bp.route('/api/stock-chart/industry-application/results/<target_id>')
def industry_application_read_result(target_id: str):
    """读某个 target 的最新 result.json。"""
    if ia_service is None:
        return jsonify({'error': 'industry_application_service 未安装'}), 501
    payload = ia_service.fetch_result(target_id)
    if payload is None:
        return jsonify({'error': 'target 不存在或 result 未生成'}), 404
    return jsonify(payload)


@stock_chart_bp.route('/api/stock-chart/industry-application/results')
def industry_application_list_results():
    """列出 reference/industry-application/results/ 下所有 json。"""
    if ia_service is None:
        return jsonify({'error': 'industry_application_service 未安装'}), 501
    return jsonify({'items': ia_service.list_all_results(), 'count': len(ia_service.list_all_results())})


@stock_chart_bp.route('/api/stock-chart/industry-application/overview')
def industry_application_overview():
    """交易日板块涨跌总览：32 申万行业 + ~50 概念主题, 一次返回。

    用来驱动 Overview Tab 的「同花顺式」长方形热力图。"""
    if ia_service is None:
        return jsonify({'error': 'industry_application_service 未安装'}), 501
    sort_by = str(request.args.get('sort_by', '涨幅')).strip() or '涨幅'
    try:
        count = int(request.args.get('count', 200))
    except (TypeError, ValueError):
        count = 200
    ascending = str(request.args.get('ascending', 'false')).strip().lower() in {'1', 'true', 'yes'}

    industry_payload = ia_service.industry_sectors_market_snapshot(
        sort_by=sort_by, count=count, ascending=ascending
    )
    concept_payload = ia_service.concept_sectors_market_snapshot(
        sort_by=sort_by, count=count, ascending=ascending
    )
    return jsonify({
        'ok': True,
        'items': (industry_payload.get('items') or []) + (concept_payload.get('items') or []),
        'industry_count': len(industry_payload.get('items') or []),
        'concept_count': len(concept_payload.get('items') or []),
        'fetched_at': industry_payload.get('fetched_at') or concept_payload.get('fetched_at'),
        'source': 'f10.list_industry_sectors_market + f10.list_concept_sectors_market',
    })


@stock_chart_bp.route('/api/stock-chart/industry-application/heatmap')
def industry_application_heatmap():
    from backend.services.stock.market_heatmap_service import build_market_heatmap
    import logging
    _log = logging.getLogger(__name__)
    # ?kind=all|industries|concepts|styles  &top_n=200
    kind = (request.args.get("kind") or "all").strip().lower()
    if kind not in ("all", "industries", "concepts", "styles"):
        kind = "all"
    try:
        top_n = int(request.args.get("top_n") or 200)
    except (TypeError, ValueError):
        top_n = 200
    try:
        payload = build_market_heatmap(kind=kind, top_n=top_n)
    except Exception as exc:
        _log.warning("build_market_heatmap failed: %s", exc)
        return jsonify({
            "ok": False,
            "kind": kind,
            "items": [],
            "totalStocks": 0,
            "fetchedAt": None,
            "source": "sectors.json + fallback (failed)",
            "error": str(exc),
        })
    return jsonify(payload)


@stock_chart_bp.route('/api/stock-chart/industry-application/tdx-industry-56')
def tdx_industry_56():
    """TDX 56 个行业指数的实时行情快照.

    URL: /api/stock-chart/industry-application/tdx-industry-56
    拉取逻辑: ``backend.services.stock.f10.tdx_industry_service``.
    """
    from backend.services.stock.f10.tdx_industry_service import (
        build_industry_market_payload,
    )
    try:
        payload = build_industry_market_payload()
        payload["ok"] = True
    except Exception as exc:
        return jsonify({
            "ok": False,
            "kind": "industries",
            "label": "行业",
            "count": 0,
            "items": [],
            "error": str(exc),
            "source": "eltdx.get_index_codes_all + get_quote (failed)",
        }), 200
    return jsonify(payload)


@stock_chart_bp.route('/api/stock-chart/industry-application/tdx-industry-kline')
def tdx_industry_kline():
    """单个 TDX 行业指数 K 线.

    URL: /api/stock-chart/industry-application/tdx-industry-kline
        ?code=880471&period=day&count=120
    """
    from backend.services.stock.f10.tdx_industry_service import fetch_industry_kline
    code = (request.args.get("code") or "").strip()
    period = (request.args.get("period") or "day").strip().lower()
    try:
        count = int(request.args.get("count") or 120)
    except (TypeError, ValueError):
        count = 120
    if not code:
        return jsonify({"ok": False, "error": "code is required", "items": []}), 400
    rows = fetch_industry_kline(code, period=period, count=count)
    return jsonify({"ok": True, "code": code, "period": period, "count": count, "items": rows})


@stock_chart_bp.route('/api/stock-chart/industry-application/tdx-industry-snapshot')
def tdx_industry_snapshot():
    """单个 TDX 行业指数实时快照.

    URL: /api/stock-chart/industry-application/tdx-industry-snapshot?code=880471
    """
    from backend.services.stock.f10.tdx_industry_service import fetch_industry_snapshot
    code = (request.args.get("code") or "").strip()
    if not code:
        return jsonify({"ok": False, "error": "code is required"}), 400
    row = fetch_industry_snapshot(code)
    if not row:
        return jsonify({"ok": False, "error": f"no quote for {code}"}), 200
    return jsonify({"ok": True, "item": row})


# ---------------------------------------------------------------------------
# Stock Overview · Market Pulse (行情页)
# ---------------------------------------------------------------------------
@stock_chart_bp.route('/api/stock-chart/market-pulse/strong')
def market_pulse_strong():
    """强势板块: TDX 56 行业指数, 按当日 change_pct 排序. URL: ?topN=10"""
    from backend.services.stock.market_pulse_service import build_strong_sectors
    try:
        top_n = int(request.args.get("topN") or 10)
    except (TypeError, ValueError):
        top_n = 10
    try:
        return jsonify(build_strong_sectors(top_n=top_n))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "top": [], "bottom": []}), 200


@stock_chart_bp.route('/api/stock-chart/market-pulse/capital-flow')
def market_pulse_capital_flow():
    """行业主力净流入: akshare 同花顺 90 行业真实资金流. URL: ?topN=20"""
    from backend.services.stock.market_pulse_service import build_capital_flow
    try:
        top_n = int(request.args.get("topN") or 20)
    except (TypeError, ValueError):
        top_n = 20
    try:
        return jsonify(build_capital_flow(top_n=top_n))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "inflow": [], "outflow": []}), 200


@stock_chart_bp.route('/api/stock-chart/market-pulse/rotation')
def market_pulse_rotation():
    """行业轮动: 读 reference/stock-universe/market_pulse/rotation/*.json 持久化数据.

    URL: ?days=10&topN=10&refresh=1
        refresh=1 强制重新抓今日快照并落盘 (其它历史日期不动).
    """
    from backend.services.stock.market_pulse_service import (
        build_industry_rotation,
        snapshot_today_rotation,
    )
    try:
        days = int(request.args.get("days") or 10)
    except (TypeError, ValueError):
        days = 10
    try:
        top_n = int(request.args.get("topN") or 10)
    except (TypeError, ValueError):
        top_n = 10
    if request.args.get("refresh") == "1":
        try:
            snapshot_today_rotation(top_n=top_n, persist=True)
        except Exception as exc:
            logger.warning("refresh rotation failed: %s", exc)
    try:
        return jsonify(build_industry_rotation(days=days, top_n=top_n))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "rows": [], "dates": []}), 200


@stock_chart_bp.route('/api/stock-chart/market-pulse/all')
def market_pulse_all():
    """一次拿三块, 行情页首屏用. URL: ?days=30&topN=10"""
    from backend.services.stock.market_pulse_service import build_market_pulse
    try:
        return jsonify(build_market_pulse())
    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
            "strong": {"ok": False, "top": [], "bottom": []},
            "flow":   {"ok": False, "inflow": [], "outflow": []},
            "rotation": {"ok": False, "rows": [], "dates": []},
        }), 200


# ---------------------------------------------------------------------------
# 历史 Top 10 趋势 (跨日)
# ---------------------------------------------------------------------------
@stock_chart_bp.route('/api/stock-chart/market-pulse/rotation-trend')
def market_pulse_rotation_trend():
    """跨日 Top 10 趋势: 给每个行业一个 (date -> rank) 序列 + 出现频次/排名迁移.

    URL: ?days=10&topN=10
    """
    from backend.services.stock.market_pulse_service import build_rotation_trend
    try:
        days = int(request.args.get("days") or 10)
    except (TypeError, ValueError):
        days = 10
    try:
        top_n = int(request.args.get("topN") or 10)
    except (TypeError, ValueError):
        top_n = 10
    try:
        return jsonify(build_rotation_trend(days=days, top_n=top_n))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "industries": [], "dates": []}), 200


# ---------------------------------------------------------------------------
# M1 卡片钻入: 行业成分股 + 领涨股
# ---------------------------------------------------------------------------
@stock_chart_bp.route('/api/stock-chart/market-pulse/industry-detail')
def market_pulse_industry_detail():
    """行业钻入: 当前 akshare 90 行业 → 成分股 + 领涨股详情.

    URL: ?name=银行&topN=30
        (按行业名匹配, akshare stock_fund_flow_industry 的"行业"字段)
    """
    from backend.services.stock.market_pulse_service import build_industry_detail
    name = (request.args.get("name") or "").strip()
    try:
        top_n = int(request.args.get("topN") or 30)
    except (TypeError, ValueError):
        top_n = 30
    if not name:
        return jsonify({"ok": False, "error": "name is required", "constituents": []}), 400
    try:
        return jsonify(build_industry_detail(name=name, top_n=top_n))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "constituents": []}), 200


# ---------------------------------------------------------------------------
# Scheduler 状态
# ---------------------------------------------------------------------------
@stock_chart_bp.route('/api/stock-chart/market-pulse-scheduler/status')
def market_pulse_scheduler_status():
    from backend.services.scheduler.market_pulse_scheduler import get_market_pulse_scheduler_status
    return jsonify(get_market_pulse_scheduler_status())


@stock_chart_bp.route('/api/stock-chart/market-pulse-scheduler/trigger', methods=['POST'])
def market_pulse_scheduler_trigger():
    """手动触发今日 snapshot (运维/测试用)."""
    from backend.services.stock.market_pulse_service import snapshot_today_rotation
    try:
        snap = snapshot_today_rotation(top_n=10, persist=True)
        return jsonify({"ok": True, "triggeredAt": snap.get("fetchedAt"), "items": snap.get("items", [])[:5]})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 200


@stock_chart_bp.route('/api/stock-chart/market-pulse-scheduler/trigger-constituents', methods=['POST'])
def market_pulse_scheduler_trigger_constituents():
    """手动触发 90 行业全量成分股刷新 (Playwright, 慢)."""
    import time as _time
    from backend.services.stock.f10.ths_industry_service import get_all_constituents
    try:
        t0 = _time.time()
        out = get_all_constituents(refresh=True)
        elapsed = round((_time.time() - t0) * 1000)
        ok_count = sum(1 for v in out.values() if v)
        return jsonify({
            "ok": True,
            "elapsedMs": elapsed,
            "industriesOk": ok_count,
            "industriesTotal": 90,
            "codes": list(out.keys()),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 200


# ---------------------------------------------------------------------------
# 同花顺行业 (akshare stock_board_industry_*_ths)
# ---------------------------------------------------------------------------
@stock_chart_bp.route('/api/stock-chart/ths-industry/list')
def ths_industry_list():
    """同花顺 90 行业列表: name + code (881xxx)."""
    from backend.services.stock.f10.ths_industry_service import get_industry_list
    try:
        refresh = request.args.get("refresh") == "1"
        items = get_industry_list(refresh=refresh)
        return jsonify({
            "ok": True,
            "count": len(items),
            "byCode": items,
            "nameToCode": {v["name"]: v["code"] for v in items.values()},
            "source": "akshare.stock_board_industry_name_ths",
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "byCode": {}, "nameToCode": {}}), 200


@stock_chart_bp.route('/api/stock-chart/ths-industry/info')
def ths_industry_info():
    """同花顺单行业 9 项实时 (今开/昨收/最高/最低/成交量/成交额/涨跌幅/涨跌额/振幅/换手率).

    URL: ?name=半导体&refresh=1   (name 或 code 都行)
    """
    from backend.services.stock.f10.ths_industry_service import get_industry_info
    name_or_code = (request.args.get("name") or request.args.get("code") or "").strip()
    if not name_or_code:
        return jsonify({"ok": False, "error": "name or code is required"}), 400
    try:
        refresh = request.args.get("refresh") == "1"
        row = get_industry_info(name_or_code, refresh=refresh)
        if not row:
            return jsonify({"ok": False, "error": f"no info for {name_or_code}"}), 200
        return jsonify({"ok": True, "item": row})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 200


@stock_chart_bp.route('/api/stock-chart/ths-industry/kline')
def ths_industry_kline():
    """同花顺行业指数 K 线 (日 K). URL: ?name=半导体&start_date=20240101&end_date=20260607&refresh=1"""
    from backend.services.stock.f10.ths_industry_service import get_industry_kline
    name_or_code = (request.args.get("name") or request.args.get("code") or "").strip()
    if not name_or_code:
        return jsonify({"ok": False, "error": "name or code is required", "rows": []}), 400
    start_date = (request.args.get("start_date") or "").strip() or None
    end_date = (request.args.get("end_date") or "").strip() or None
    period = (request.args.get("period") or "day").strip().lower()
    try:
        refresh = request.args.get("refresh") == "1"
        rows = get_industry_kline(name_or_code, period=period, start_date=start_date, end_date=end_date, refresh=refresh)
        return jsonify({"ok": True, "name": name_or_code, "period": period, "count": len(rows), "rows": rows})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "rows": []}), 200


@stock_chart_bp.route('/api/stock-chart/individual/main-fund-flow')
def individual_main_fund_flow():
    """个股所属板块 30 天主力/大/中/小单资金流 (eltdx 200742).

    URL: ?code=sh600519&limit=30

    重要: eltdx 200742 接口对个股只能拿到"该股所属板块"30 天资金,
    不是"该股自身"30 天资金. 响应里会返 ``sectorName`` 字段标明归属板块.
    """
    from backend.services.stock.sector_quote_service import get_main_capital_flow
    code = (request.args.get("code") or "").strip()
    if not code:
        return jsonify({"ok": False, "error": "code is required", "rows": []}), 400
    try:
        limit = int(request.args.get("limit") or 30)
    except (TypeError, ValueError):
        limit = 30
    limit = max(1, min(120, limit))
    try:
        rows = get_main_capital_flow(code) or []
        if limit and limit < len(rows):
            rows = rows[:limit]
        sector_name = rows[0].get("sector_name") if rows else None
        # 计算连入/连出天数 + 累计净额
        streak = 0
        sign = 0
        for r in rows:
            v = r.get("main_net") or 0
            if v == 0:
                break
            if sign == 0:
                sign = 1 if v > 0 else -1
                streak = 1
            elif (v > 0 and sign > 0) or (v < 0 and sign < 0):
                streak += 1
            else:
                break
        main_sum = sum(float(r.get("main_net") or 0) for r in rows)
        return jsonify({
            "ok": True,
            "code": code,
            "sectorName": sector_name,
            "count": len(rows),
            "mainNetSum": main_sum,
            "consecutiveDays": streak if sign != 0 else 0,
            "note": "eltdx f10 200742 接口对个股只能拿到该股所属板块的资金, 不是该股自身资金. "
                    "前端展示时建议标注 '所属于板块'.",
            "rows": rows,
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "rows": []}), 200


# ---------------------------------------------------------------------------
# qt.gtimg.cn 个股资金流 (88 字段主接口 + s_pk 盘口)
# ---------------------------------------------------------------------------
@stock_chart_bp.route('/api/stock-chart/qt/fund-flow')
def qt_fund_flow():
    """qt.gtimg.cn 个股资金流 (主接口 88 字段 + 盘口占比 s_pk).

    URL: ?code=sh600519&refresh=1
        (code 形如 sh600519 / sz000858 / bj830799)

    返回字段:
      code, name, lastPrice, preClose, open, high, low,
      change, changePct, amountWan, turnoverRate, pe, pb, amplitude,
      volumeLots (成交量手), outerDisc (外盘手=主动买入), insideDish (内盘手=主动卖出),
      activeNetLots (主动净流入手), activeNetAmountWan (折算成元/万),
      activeBuyRatio, activeSellRatio,          # 主动买卖占比 0~1
      disk.{buyBigRatio, buySmallRatio, sellBigRatio, sellSmallRatio}  # 盘口大单/小单占比
    """
    from backend.services.stock.f10.qt_fund_flow_service import fetch_qt_fund_flow
    code = (request.args.get("code") or "").strip()
    if not code:
        return jsonify({"ok": False, "error": "code is required"}), 400
    refresh = request.args.get("refresh") == "1"
    try:
        blob = fetch_qt_fund_flow(code, refresh=refresh)
        if not blob:
            return jsonify({"ok": False, "error": f"no data for {code}"}), 200
        return jsonify({"ok": True, **blob})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 200


@stock_chart_bp.route('/api/stock-chart/qt/fund-flow-batch')
def qt_fund_flow_batch():
    """qt.gtimg.cn 个股资金流批量 (q=a,b,c 一次 200ms).

    URL: ?codes=sh600519,sh601398,sz000858&refresh=1
    """
    from backend.services.stock.f10.qt_fund_flow_service import fetch_qt_fund_flow_batch
    codes_param = (request.args.get("codes") or "").strip()
    if not codes_param:
        return jsonify({"ok": False, "error": "codes is required, comma separated", "data": {}}), 400
    codes = [c.strip() for c in codes_param.split(",") if c.strip()]
    if len(codes) > 80:
        return jsonify({"ok": False, "error": "max 80 codes per request"}), 400
    refresh = request.args.get("refresh") == "1"
    try:
        out = fetch_qt_fund_flow_batch(codes, refresh=refresh)
        return jsonify({"ok": True, "count": len(out), "data": out})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "data": {}}), 200


# ---------------------------------------------------------------------------
# 同花顺行业 (akshare stock_board_industry_*_ths)
# ---------------------------------------------------------------------------
def ths_industry_payload():
    """一次拿三块: 90 行业列表 + 9 项实时聚合."""
    from backend.services.stock.f10.ths_industry_service import build_industry_payload
    try:
        return jsonify(build_industry_payload())
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "items": []}), 200


@stock_chart_bp.route('/api/stock-chart/ths-industry/constituents')
def ths_industry_constituents():
    """同花顺行业成分股 (按 name 查, 内部走 hexin-v 破解新版).

    URL: ?name=半导体&refresh=1    (name 走 ths_industry_service.name_to_code() 解析)
    返回字段: rows 是 14 列 pandas 解析的 dict (跟 constituents-by-code 一致)
    """
    from backend.services.stock.f10.ths_industry_service import (
        code_to_name,
        name_to_code,
    )
    from backend.services.stock.f10.ths_industry_constituents_service import (
        get_industry_constituents,
    )
    name_or_code = (request.args.get("name") or request.args.get("code") or "").strip()
    if not name_or_code:
        return jsonify({"ok": False, "error": "name or code is required", "rows": []}), 400
    # 解析: 数字 6 位 -> code, 其它 -> name -> code
    if name_or_code.isdigit() and len(name_or_code) == 6:
        code = name_or_code
        target_name = code_to_name(code) or name_or_code
    else:
        code = name_to_code(name_or_code) or ""
        target_name = name_or_code
    if not code:
        return jsonify({
            "ok": False,
            "error": f"unknown industry: {name_or_code}",
            "rows": [],
        }), 404
    try:
        refresh = request.args.get("refresh") == "1"
        payload = get_industry_constituents(code, refresh=refresh)
        rows = payload.get("rows") or []
        return jsonify({
            "ok": True,
            "name": target_name,
            "code": code,
            "totalPages": payload.get("totalPages") or 0,
            "pageRowCounts": payload.get("pageRowCounts") or [],
            "count": len(rows),
            "rows": rows,
            "fetchedAt": payload.get("fetchedAt"),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "rows": []}), 200


@stock_chart_bp.route('/api/stock-chart/ths-industry/constituents-all')
def ths_industry_constituents_all():
    """90 行业全量成分股 (单线程, 慢, 8s/行业). URL: ?refresh=1

    走新 hexin-v 爬虫; 调 ``get_all_constituents_v2`` (新模块)
    """
    from backend.services.stock.f10.ths_industry_constituents_service import (
        get_all_industry_constituents,
    )
    try:
        refresh = request.args.get("refresh") == "1"
        out = get_all_industry_constituents(refresh=refresh)
        return jsonify({"ok": True, "count": len(out), "industries": list(out.keys()), "byCode": out})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "byCode": {}}), 200


# ---------------------------------------------------------------------------
# 同花顺全行业主力资金 (hexin-v 破解, py_mini_racer + ths.js)
# 数据源: http://data.10jqka.com.cn/funds/hyzj1/
# 字段: rank/industry/change_pct/inflow/outflow/net/company_count/
#       leader_stock/leader_change/leader_price
# 落盘: reference/ths-fund-flow/latest.json + history/yyyy-mm-dd.json
# ---------------------------------------------------------------------------
@stock_chart_bp.route('/api/stock-chart/ths-industry/fund-flow')
def ths_industry_fund_flow():
    """同花顺全行业主力资金动向.

    URL: ?refresh=1 (强制重爬) &top=10 (只返 top N, 按净额 desc)

    路由:
      GET /api/stock-chart/ths-industry/fund-flow           读 latest.json
      GET /api/stock-chart/ths-industry/fund-flow?refresh=1 强制重爬 + 写盘
      GET /api/stock-chart/ths-industry/fund-flow?top=10    读 latest, 截前 10
    """
    from backend.services.stock.f10.ths_fund_flow_service import (
        get_industry_fund_flow,
    )
    refresh = request.args.get("refresh") == "1"
    top_param = (request.args.get("top") or "").strip()
    try:
        top = int(top_param) if top_param else None
    except (TypeError, ValueError):
        top = None
    if top is not None:
        top = max(1, min(200, top))

    try:
        payload = get_industry_fund_flow(refresh=refresh)
        rows = payload.get("rows") or []
        # 每行 enrich 一个 ``code`` 字段 (6 位行业 code, 从 industry_list.json 解析)
        # 前端不再需要把中文 name 再 name→code 一次, 直接拿 code 调成分股接口
        from backend.services.stock.f10.ths_industry_service import name_to_code
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("code"):
                continue
            industry_name = row.get("行业")
            if isinstance(industry_name, str) and industry_name:
                row["code"] = name_to_code(industry_name) or None
        if top is not None and len(rows) > top:
            rows = rows[:top]
            payload = dict(payload)
            payload["rows"] = rows
            payload["rowCount"] = len(rows)
        return jsonify(payload)
    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
            "rows": [],
            "rowCount": 0,
            "fetchedAt": None,
        }), 200


@stock_chart_bp.route('/api/stock-chart/ths-industry/fund-flow/refresh', methods=['POST'])
def ths_industry_fund_flow_refresh():
    """POST 强制刷新, 同步等结果 (前端 loading 用).

    URL: POST /api/stock-chart/ths-industry/fund-flow/refresh
    """
    from backend.services.stock.f10.ths_fund_flow_service import (
        refresh_industry_fund_flow,
    )
    try:
        payload = refresh_industry_fund_flow()
        return jsonify({"ok": True, **payload})
    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
            "rows": [],
            "rowCount": 0,
        }), 200


@stock_chart_bp.route('/api/stock-chart/ths-industry/fund-flow/history')
def ths_industry_fund_flow_history():
    """列出 / 读取 历史归档.

    URL: GET /api/stock-chart/ths-industry/fund-flow/history
    URL: GET /api/stock-chart/ths-industry/fund-flow/history?date=2026-06-08
    """
    from backend.services.stock.f10.ths_fund_flow_service import (
        list_history_dates,
        read_history,
    )
    date_param = (request.args.get("date") or "").strip()
    if date_param:
        payload = read_history(date_param)
        if payload is None:
            return jsonify({
                "ok": False,
                "error": f"no history for {date_param}",
                "rows": [],
                "rowCount": 0,
            }), 404
        return jsonify({"ok": True, "date": date_param, **payload})
    return jsonify({
        "ok": True,
        "dates": list_history_dates(),
    })


# ---------------------------------------------------------------------------
# 同花顺行业成分股 (hexin-v 破解, q.10jqka.com.cn/thshy/detail/code/{n}/page/{n}/)
# 字段: 序号/代码/名称/现价/涨跌幅(%)/涨跌/涨速(%)/换手(%)/量比/振幅(%)/
#       成交额/流通股/流通市值/市盈率
# 落盘: reference/stock-universe/ths_industry/constituents/{code}.json
# 跟老 /api/stock-chart/ths-industry/constituents 路由分开, 独立 API
# ---------------------------------------------------------------------------
@stock_chart_bp.route('/api/stock-chart/ths-industry/constituents-by-code')
def ths_industry_constituents_by_code():
    """同花顺行业成分股 (按 6 位 code 爬, hexin-v 破解, q.10jqka 翻全页).

    URL: ?code=881268&refresh=1
         (code 形如 881268, 跟 ths_industry_service.get_industry_list() 的 code 字段一致)

    返回:
      ok, code, totalPages, pageRowCounts, fetchedAt, rowCount, rows[14 列]
    """
    from backend.services.stock.f10.ths_industry_constituents_service import (
        get_industry_constituents,
    )
    code = (request.args.get("code") or "").strip()
    if not code:
        return jsonify({"ok": False, "error": "code is required", "rows": [], "rowCount": 0}), 400
    refresh = request.args.get("refresh") == "1"
    try:
        payload = get_industry_constituents(code, refresh=refresh)
        return jsonify(payload)
    except Exception as exc:
        return jsonify({
            "ok": False,
            "code": code,
            "error": str(exc),
            "rows": [],
            "rowCount": 0,
        }), 200


@stock_chart_bp.route('/api/stock-chart/ths-industry/constituents-by-code/refresh', methods=['POST'])
def ths_industry_constituents_by_code_refresh():
    """POST 强制刷新, 同步等结果 (前端 loading 用).

    URL: POST /api/stock-chart/ths-industry/constituents-by-code/refresh?code=881268
    """
    from backend.services.stock.f10.ths_industry_constituents_service import (
        refresh_industry_constituents,
    )
    code = (request.args.get("code") or "").strip()
    if not code:
        return jsonify({"ok": False, "error": "code is required", "rows": [], "rowCount": 0}), 400
    try:
        payload = refresh_industry_constituents(code)
        return jsonify({"ok": True, **payload})
    except Exception as exc:
        return jsonify({
            "ok": False,
            "code": code,
            "error": str(exc),
            "rows": [],
            "rowCount": 0,
        }), 200


@stock_chart_bp.route('/api/stock-chart/ths-industry/constituents-by-code/cached')
def ths_industry_constituents_by_code_cached():
    """列出本地已落盘的行业 code (用于前端快速预览, 不爬网络).

    URL: GET /api/stock-chart/ths-industry/constituents-by-code/cached
    """
    from backend.services.stock.f10.ths_industry_constituents_service import (
        list_cached_codes,
    )
    return jsonify({
        "ok": True,
        "codes": list_cached_codes(),
    })


@stock_chart_bp.route('/api/stock-chart/ths-industry/constituents-file')
def ths_industry_constituents_file():
    """读磁盘落盘, 不爬网络. 单一来源: reference/ths-industry/constituents/{code}.json.

    URL: ?name=半导体  或  ?code=881157
    适用: 资金流 drawer 「打开默认」高频场景, 避免每次都打 q.10jqka 触发 hexin-v
    数据流:
      - 交易日 17:00 由 ths_industry_constituents_daily_scheduler 收盘后 hexin-v 重爬落盘
      - 非交易时间 / 周末 / 节假日: 永远读磁盘 (不会反复爬, drawer 自动拿到 17:00 那次最新落盘)
    返回: 14 列完整行情 + 元信息 (isTradingDay / tradingHoursMode / snapshotDate / dataSource)
    """
    from backend.services.stock.f10.ths_industry_service import (
        code_to_name,
        name_to_code,
    )
    from backend.services.stock.f10.ths_industry_constituents_service import (
        read_industry_constituents_joined,
    )
    from backend.services.stock.trading_calendar import (
        is_trade_time,
        is_trading_day,
        previous_trading_day,
    )

    name_or_code = (request.args.get("name") or request.args.get("code") or "").strip()
    if not name_or_code:
        return jsonify({"ok": False, "error": "name or code is required", "rows": []}), 400
    if name_or_code.isdigit() and len(name_or_code) == 6:
        code = name_or_code
        target_name = code_to_name(code) or name_or_code
    else:
        code = name_to_code(name_or_code) or ""
        target_name = name_or_code
    if not code:
        return jsonify({
            "ok": False,
            "error": f"unknown industry: {name_or_code}",
            "rows": [],
        }), 404

    payload = read_industry_constituents_joined(code)
    if not payload:
        return jsonify({
            "ok": False,
            "code": code,
            "error": f"no persisted constituents for {code} "
                     f"(reference/ths-industry/constituents/{code}.json 不存在, "
                     f"请等 17:00 收盘后 hexin-v 自动落盘, 或手动调 trigger_ths_industry_constituents_daily)",
            "rows": [],
        }), 404

    # 交易时间窗状态 (用于前端判断 "这是今日实时" 还是 "上一交易日收盘")
    is_td = is_trading_day()
    is_open = is_trade_time()
    if is_td and is_open:
        trading_hours_mode = "trading"   # 9:30-11:30 / 13:00-15:00 盘内
    elif is_td:
        trading_hours_mode = "trading_day_off_hours"  # 交易日但非盘内 (午休 / 收盘后)
    else:
        trading_hours_mode = "non_trading_day"  # 周末 / 节假日

    # 数据快照日期 (17:00 后: 今日, 17:00 前: 上一交易日)
    snapshot_date = (
        _beijing_today()
        if (is_td and _beijing_now().hour >= 17)
        else previous_trading_day()
    )

    return jsonify({
        "ok": True,
        "name": payload.get("name") or target_name,
        "code": code,
        "count": payload.get("count") or 0,
        "matched": payload.get("matched") or 0,
        "rowsFetchedAt": payload.get("rowsFetchedAt"),
        "rows": payload.get("rows") or [],
        # 持久化 / 交易时间窗元信息
        "dataSource": "disk",       # 这个端点永远读磁盘, 不爬网络
        "isTradingDay": is_td,
        "isMarketOpen": is_open,
        "tradingHoursMode": trading_hours_mode,
        "snapshotDate": snapshot_date.isoformat() if snapshot_date else None,
    })


# ---------------------------------------------------------------------------
# Style Sectors (风格板块, 29 个)
# 读 sectors_styles_4.json → 实时行情 → 等权平均 (走 infra.style_sector.compute_sector_change_pct)
# ---------------------------------------------------------------------------
@stock_chart_bp.route('/api/stock-chart/style-sectors', methods=['GET'])
def style_sectors_all():
    """29 个 style sectors 板块涨跌幅 (一次拉完)."""
    from backend.services.stock.style_sector_service import (
        get_all_style_sectors,
        STYLE_SECTOR_NAMES,
    )
    try:
        items = get_all_style_sectors()
        return jsonify({
            "ok": True,
            "items": items,
            "count": len(items),
            "names": STYLE_SECTOR_NAMES,
        })
    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
            "items": [],
            "count": 0,
            "names": STYLE_SECTOR_NAMES,
        }), 200


@stock_chart_bp.route('/api/stock-chart/style-sectors/<string:name>', methods=['GET'])
def style_sector_one(name: str):
    """单个 style 板块涨跌幅. name 走 URL decode (中文 OK)."""
    from backend.services.stock.style_sector_service import get_style_sector
    try:
        result = get_style_sector(name)
    except Exception as exc:
        return jsonify({"ok": False, "name": name, "error": str(exc)}), 200
    if result is None:
        return jsonify({"ok": False, "error": f"unknown style: {name}"}), 404
    return jsonify({"ok": True, "item": result})
