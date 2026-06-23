from datetime import datetime, timedelta
from typing import Any

import logging

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 北京时间 (UTC+8) 辅助, 给 ths_industry_constituents_file 用
# ---------------------------------------------------------------------------
def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _beijing_today():
    return _beijing_now().date()

from backend.adapters.market.eastmoney import fetch_stock_meta, fetch_market_breadth
from backend.adapters.market.eltdx_adapter import fetch_stock_klines_from_eltdx
from backend.adapters.market.tencent import fetch_stock_klines_from_tencent
from backend.config.settings import STOCK_REFERENCE_CACHE_FOLDER
from backend.repositories.stock.workspace_repo import read_cached_stock_intraday, stock_kline_cache_file
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
from backend.services.stock.limit_emotion_service import (
    build_limit_emotion as _build_limit_emotion_service,
    get_limit_emotion as _get_limit_emotion_service,
    snapshot_today_daily as _snapshot_today_daily_service,
    save_config as _save_limit_emotion_config,
)
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


def _latest_market_sentiment_trade_date_str() -> str:
    """返回 Market Sentiment 页面默认展示日: 含今天的最近交易日."""
    from datetime import date as _date
    from backend.services.stock.trading_day_resolver import (
        resolve_target_trading_day_safe,
    )

    resolved = resolve_target_trading_day_safe()
    return resolved.isoformat() if resolved is not None else _date.today().isoformat()


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


def _load_persisted_index_intraday_snapshot(code: str, trade_date: str, interval: str) -> tuple[dict | None, str | None]:
    """优先读持久化的 intraday cache，避免历史分钟K退化成异常占位数据。"""
    cached_snapshot = read_cached_stock_intraday('index', code, trade_date)
    if not isinstance(cached_snapshot, dict):
        return None, None

    if str(cached_snapshot.get('trade_date') or '').strip() != trade_date:
        return None, None

    minute_bars = cached_snapshot.get('minute_bars')
    if not isinstance(minute_bars, dict):
        return None, None

    bars = minute_bars.get(interval)
    if not isinstance(bars, list) or not bars:
        return None, None

    period_sources = cached_snapshot.get('period_sources')
    period_source = None
    if isinstance(period_sources, dict):
        source_value = period_sources.get(interval)
        if isinstance(source_value, str) and source_value.strip():
            period_source = source_value.strip()

    return cached_snapshot, period_source or 'persisted-cache'


def _is_valid_ohlc_minute_bar(bar: dict) -> bool:
    try:
        timestamp = float(bar.get('timestamp') or 0)
        open_price = float(bar.get('open'))
        high_price = float(bar.get('high'))
        low_price = float(bar.get('low'))
        close_price = float(bar.get('close'))
    except (TypeError, ValueError):
        return False

    if timestamp <= 0:
        return False
    if min(open_price, high_price, low_price, close_price) <= 0:
        return False
    return high_price >= max(open_price, close_price) and low_price <= min(open_price, close_price)


def _has_renderable_kline_shape(bars: list[dict]) -> bool:
    for bar in bars:
        try:
            open_price = float(bar.get('open'))
            high_price = float(bar.get('high'))
            low_price = float(bar.get('low'))
            close_price = float(bar.get('close'))
        except (TypeError, ValueError):
            continue
        if high_price > low_price or open_price != close_price:
            return True
    return False


def _usable_index_minute_bars(snapshot: dict, interval: str) -> list[dict]:
    minute_bars = snapshot.get('minute_bars')
    if not isinstance(minute_bars, dict):
        return []
    raw_bars = minute_bars.get(interval)
    if not isinstance(raw_bars, list):
        return []
    bars = [bar for bar in raw_bars if isinstance(bar, dict) and _is_valid_ohlc_minute_bar(bar)]
    if not _has_renderable_kline_shape(bars):
        return []
    return bars


def _derive_index_minute_bars_from_timeshare(snapshot: dict, trade_date: str) -> list[dict]:
    timeshare = snapshot.get('timeshare')
    if not isinstance(timeshare, list):
        return []

    bars: list[dict] = []
    previous_close: float | None = None
    for point in sorted(
        (item for item in timeshare if isinstance(item, dict)),
        key=lambda row: float(row.get('timestamp') or 0),
    ):
        try:
            timestamp = int(float(point.get('timestamp') or 0))
            close_price = float(point.get('price'))
        except (TypeError, ValueError):
            continue
        if timestamp <= 0 or close_price <= 0:
            continue

        point_trade_date = str(point.get('trade_date') or trade_date or '').strip()
        open_price = previous_close if previous_close and previous_close > 0 else close_price
        high_price = max(open_price, close_price)
        low_price = min(open_price, close_price)
        volume = point.get('volume')
        turnover = point.get('turnover')
        bars.append({
            'timestamp': timestamp,
            'trade_date': point_trade_date,
            'open': open_price,
            'high': high_price,
            'low': low_price,
            'close': close_price,
            'volume': volume if isinstance(volume, (int, float)) else 0,
            'turnover': turnover if isinstance(turnover, (int, float)) else 0,
            'derived_from': 'timeshare',
        })
        previous_close = close_price

    if not _has_renderable_kline_shape(bars):
        return []
    return bars



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


# ---------------------------------------------------------------------------
# 三大指数 1m K 批量接口 (Market Pulse 联动用)
# ---------------------------------------------------------------------------
# code → 中文名 (跟 market_overview.style_rotation.INDEX_SYMBOLS 保持一致)
_INDEX_CODE_TO_NAME = {
    '000001': '上证指数',
    '399001': '深证成指',
    '000300': '沪深300',
    '000016': '上证50',
    '000905': '中证500',
    '000852': '中证1000',
    '932000': '中证2000',
    '399006': '创业板指',
    '000688': '科创50',
}


def _normalize_index_code(raw: str) -> str:
    """兼容 'sh000001' / 'sz399001' → '000001' / '399001' (跟现有 target_type=index 约定一致)."""
    c = (raw or '').strip()
    if not c:
        return ''
    lower = c.lower()
    if lower.startswith(('sh', 'sz')):
        c = c[2:]
    return c


def _resolve_previous_close_for_index(code: str, target_date: str) -> float | None:
    """取上一交易日的 1d K 最后 close (失败返回 None, 不阻塞主流程).

    修复历史: 之前调 resolve_stock_klines 走完整 plan, 但 plan 里有 provider
    异常静默被吞, fallback 到 sample loader → items=[], prev_close 永远 None.
    现在直接调 fetch_stock_klines_from_eltdx (plan 第一个, 毫秒级), 显式 fallback 到
    tencent, 都不行再 None. 少一层包装, 日志可观测.
    """
    for fetcher in (
        lambda: fetch_stock_klines_from_eltdx('index', code, '1d', 'none'),
        lambda: fetch_stock_klines_from_tencent('index', code, '1d', 'none'),
    ):
        try:
            items = fetcher()
        except Exception:
            continue
        # 显式按 trade_date 降序, 拿第一个 < target_date 的 bar (即"上一交易日").
        # provider 返回顺序不保证 (eltdx 可能是 asc, tencent 可能是 desc), 不排序会拿到
        # 2 年前的旧 bar, previousClose 会差几千点, 涨幅显示完全错乱.
        sorted_items = sorted(
            (bar for bar in (items or []) if (bar.get('trade_date') or '').strip()),
            key=lambda b: b.get('trade_date') or '',
            reverse=True,
        )
        for bar in sorted_items:
            td = (bar.get('trade_date') or '').strip()
            if not td or td >= target_date:
                continue
            try:
                close_val = float(bar.get('close') or 0)
            except (TypeError, ValueError):
                continue
            if close_val > 0:
                return close_val
    return None
    prev_close: float | None = None
    for bar in items or []:
        td = (bar.get('trade_date') or '').strip()
        if not td or td >= target_date:
            continue
        try:
            close_val = float(bar.get('close') or 0)
        except (TypeError, ValueError):
            continue
        if close_val > 0:
            prev_close = close_val
    return prev_close


@stock_chart_bp.route('/api/index-kline/batch')
def index_kline_batch():
    """三大指数 1m K 批量接口 (Market Pulse 顶部 3 卡联动用).

    Query:
      codes: 逗号分隔, 例 "000001,399001,399006" 或 "sh000001,sz399001,sz399006"
             默认 000001,399001,399006 (上证 / 深证 / 创业板)
      date:  YYYY-MM-DD, 必填
      interval: 周期, 目前只支持 1m

    Response:
      { ok, date, interval, items: [{ code, name, date, interval, previousClose,
                                       source, points: [{time, open, high, low, close, volume, turnover}],
                                       error? }] }
    """
    raw_codes = str(request.args.get('codes', '000001,399001,399006')).strip()
    trade_date = str(request.args.get('date', '')).strip()
    interval = str(request.args.get('interval', '1m')).strip() or '1m'

    if interval != '1m':
        return jsonify({
            'ok': False,
            'error': f'unsupported interval: {interval} (only 1m supported)',
            'items': [],
        }), 400
    if not trade_date:
        return jsonify({
            'ok': False,
            'error': 'date query param required (YYYY-MM-DD)',
            'items': [],
        }), 400

    codes: list[str] = []
    for token in raw_codes.split(','):
        norm = _normalize_index_code(token)
        if norm and norm not in codes:
            codes.append(norm)
    if not codes:
        return jsonify({'ok': False, 'error': 'no valid codes', 'items': []}), 400

    items: list[dict] = []
    for code in codes:
        try:
            snapshot, source = _load_persisted_index_intraday_snapshot(code, trade_date, interval)
            if snapshot is None:
                snapshot, source = build_intraday_snapshot(
                    'index', code, 'none', sample_stock_klines,
                    trade_date=trade_date, periods=[interval],
                )
            bars = _usable_index_minute_bars(snapshot, interval)
            if not bars:
                bars = _derive_index_minute_bars_from_timeshare(snapshot, trade_date)
                if bars and source:
                    source = f'{source}-timeshare-derived'
            if not bars:
                raise ValueError(f'{trade_date} {code} 未获取到可渲染的 {interval} OHLC 数据')
            points: list[dict] = []
            for bar in sorted(bars, key=lambda row: float(row.get('timestamp') or 0)):
                ts = bar.get('timestamp')
                if not isinstance(ts, (int, float)):
                    continue
                td = (bar.get('trade_date') or trade_date or '').strip()
                time_label = datetime.fromtimestamp(float(ts) / 1000).strftime('%H:%M:%S')
                points.append({
                    'time': f'{td} {time_label}' if td else time_label,
                    'timestamp': int(ts),
                    'open': bar.get('open'),
                    'high': bar.get('high'),
                    'low': bar.get('low'),
                    'close': bar.get('close'),
                    'volume': bar.get('volume'),
                    'turnover': bar.get('turnover'),
                })

            previous_close = _resolve_previous_close_for_index(code, trade_date)

            items.append({
                'ok': True,
                'code': code,
                'name': _INDEX_CODE_TO_NAME.get(code, code),
                'date': trade_date,
                'interval': interval,
                'previousClose': previous_close,
                'source': source,
                'points': points,
            })
        except Exception as exc:
            items.append({
                'ok': False,
                'code': code,
                'name': _INDEX_CODE_TO_NAME.get(code, code),
                'date': trade_date,
                'interval': interval,
                'previousClose': None,
                'error': str(exc),
                'points': [],
            })

    return jsonify({
        'ok': True,
        'date': trade_date,
        'interval': interval,
        'items': items,
    })


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
    """按交易日 (YYYY-MM-DD 或 YYYYMMDD) 读历史 snapshot. PG → JSON 兜底."""
    # Normalise date format
    td = trading_date.replace("-", "")
    if len(td) == 8 and td.isdigit():
        iso_date = f"{td[:4]}-{td[4:6]}-{td[6:8]}"
    else:
        iso_date = trading_date

    # 1) Try PG
    try:
        from backend.config.database import session_scope
        from backend.repositories.market.market_overview_pg_repo import MarketOverviewPgRepository

        with session_scope() as db:
            repo = MarketOverviewPgRepository(db)
            row = repo.get(iso_date)
        if row:
            return jsonify(row)
    except Exception as exc:
        logger.warning("market overview archive from PG failed, fallback: %s", exc)

    # 2) Fallback: JSON
    from backend.services.stock.market_overview_akshare_service import get_archived_snapshot
    snap = get_archived_snapshot(trading_date)
    if snap is None:
        return jsonify({"ok": False, "error": f"archive {trading_date} not found"}), 404
    return jsonify(snap)


@stock_chart_bp.route('/api/stock-chart/market-overview-akshare/history')
def stock_chart_market_overview_akshare_history():
    """最近 N 个交易日的历史序列 (Market Pulse 趋势图用).

    URL: GET /api/stock-chart/market-overview-akshare/history?range=60d
    range 接受: 20d / 60d / 120d / 1y (默认 60d, 上限 365d)

    数据源优先级: PostgreSQL (主) → JSON archive (兜底)

    返回:
      {
        "ok": true,
        "range": "60d",
        "source": "postgres | eastmoney",
        "count": 60,
        "items": [
          {"date": "2025-12-11", "totalAmount": null, "risingCount": null,
           "mainNetInflow": -857.75, "superLargeNetInflow": -510.11, ...},
          ...
        ]
      }
    """
    range_param = (request.args.get("range") or "60d").strip().lower()
    days_map = {"20d": 20, "60d": 60, "120d": 120, "1y": 260}
    days = days_map.get(range_param, 60)
    days = max(1, min(days, 365))

    # 1) Try PostgreSQL first
    try:
        from backend.config.database import session_scope
        from backend.repositories.market.market_overview_pg_repo import MarketOverviewPgRepository

        with session_scope() as db:
            repo = MarketOverviewPgRepository(db)
            pg_items = repo.get_history(days=days)

        if pg_items:
            # Convert snake_case → camelCase for frontend compatibility
            items = []
            for pt in pg_items:
                items.append({
                    "date": pt.get("trade_date"),
                    "totalAmount": pt.get("total_amount"),
                    "totalVolume": pt.get("total_volume"),
                    "risingCount": pt.get("rising_count"),
                    "fallingCount": pt.get("falling_count"),
                    "flatCount": pt.get("flat_count"),
                    "limitUpCount": pt.get("limit_up_count"),
                    "limitDownCount": pt.get("limit_down_count"),
                    "stockCount": pt.get("stock_count"),
                    "mainNetInflow": pt.get("main_net_inflow"),
                    "superLargeNetInflow": pt.get("super_large_net_inflow"),
                    "largeNetInflow": pt.get("large_net_inflow"),
                    "mediumNetInflow": pt.get("medium_net_inflow"),
                    "smallNetInflow": pt.get("small_net_inflow"),
                    "mainNetInflowRatio": pt.get("main_net_inflow_ratio"),
                    "superLargeNetInflowRatio": pt.get("super_large_net_ratio"),
                    "largeNetInflowRatio": pt.get("large_net_ratio"),
                    "mediumNetInflowRatio": pt.get("medium_net_ratio"),
                    "smallNetInflowRatio": pt.get("small_net_ratio"),
                    "source": pt.get("source"),
                })
            return jsonify({
                "ok": True,
                "range": range_param,
                "source": "postgres",
                "count": len(items),
                "items": items,
            })
    except Exception as exc:
        logger.warning("market overview history from PG failed, fallback to JSON: %s", exc)

    # 2) Fallback: JSON archive
    from backend.services.stock.market_overview_akshare_service import get_history_points
    items = get_history_points(days=days)
    return jsonify({
        "ok": True,
        "range": range_param,
        "source": "eastmoney",
        "count": len(items),
        "items": items,
    })


# =============================================================================
# 市场概况 (eltdx): 全A成交额 / 涨跌家数
# 路径: /market-overview-eltdx/ (独立于 /market-overview-akshare/ fund-flow)
# 数据由 backend/services/stock/market_overview_eltdx_service.py 维护.
# 独立持久化: reference/market-overview/market-overview/latest.json
# =============================================================================
@stock_chart_bp.route('/api/stock-chart/market-overview-eltdx')
def stock_chart_market_overview_eltdx():
    """读 eltdx overview latest (全A成交额 / 涨跌家数)."""
    from backend.services.stock.market_overview_eltdx_service import get_latest_overview
    try:
        return jsonify(get_latest_overview())
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@stock_chart_bp.route('/api/stock-chart/market-overview-eltdx/refresh', methods=['POST'])
def stock_chart_market_overview_eltdx_refresh():
    """手动触发 eltdx overview 拉取 + 落盘."""
    from backend.services.stock.market_overview_eltdx_service import capture_overview
    try:
        snap = capture_overview(force=True)
        if snap is None:
            return jsonify({"ok": False, "error": "eltdx unavailable"}), 502
        return jsonify({"ok": True, "snapshot": snap})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# =============================================================================
# 手动粘贴的资金流 (东方财富资金流页面 copy-paste 兜底)
# 持久化: reference/market-overview/fund-flow/manual/YYYYMMDD.json
# 跟 akshare / eltdx overview 并行 — 前端 manual 存在时优先用 manual 覆盖.
# =============================================================================

@stock_chart_bp.route('/api/stock-chart/market-overview-manual-fund-flow', methods=['GET'])
def stock_chart_manual_fund_flow_get():
    """读指定 tradingDate 的 manual 资金流数据 (?tradingDate=YYYY-MM-DD, 默认今天)."""
    from datetime import datetime, timedelta
    from backend.services.stock.market_overview_manual_fund_flow_service import load_manual_fund_flow
    trading_date = str(request.args.get('tradingDate', '')).strip()
    if not trading_date:
        trading_date = (datetime.utcnow() + timedelta(hours=8)).strftime('%Y-%m-%d')
    data = load_manual_fund_flow(trading_date)
    if not data:
        return jsonify({"ok": False, "error": "no manual data", "tradingDate": trading_date}), 404
    return jsonify({"ok": True, **data})


@stock_chart_bp.route('/api/stock-chart/market-overview-manual-fund-flow', methods=['POST'])
def stock_chart_manual_fund_flow_post():
    """保存 manual 资金流数据.

    Body: {tradingDate: "YYYY-MM-DD", mainNetInflow: 685.17, mainNetInflowRatio: 2.26, ...}
    tradingDate 必填, 其余 10 个字段 (4 单净流入 + 4 单净比 + 主力净流入 + 主力净比) 可选.
    """
    from backend.services.stock.market_overview_manual_fund_flow_service import save_manual_fund_flow
    body = request.get_json(silent=True) or {}
    trading_date = str(body.get('tradingDate') or '').strip()
    if not trading_date:
        return jsonify({"ok": False, "error": "tradingDate required"}), 400
    try:
        saved = save_manual_fund_flow(trading_date, body)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, **saved})


# =============================================================================
# 大盘概况 duckdb 历史序列 (持久化到 market_overview_daily 表)
# 跟 /market-overview-akshare/history (读 JSON archive) 是两条独立路径, 字段一致
# 用途: 跨日趋势 / 量价分析 / 历史回测
# =============================================================================

@stock_chart_bp.route('/api/stock-chart/market-overview/history')
def stock_chart_market_overview_history():
    """读 duckdb.market_overview_daily 的近 N 天历史 (字段级: akshare 资金流 + eltdx 涨跌家数).

    URL: ?days=60 (1-365, 默认 60) &start=YYYY-MM-DD (默认 end-days) &end=YYYY-MM-DD (默认今天)
    """
    from datetime import date as _date, timedelta
    from backend.repositories.market.market_overview_repo import get_overview_history
    try:
        end_str = (request.args.get("end") or "").strip()
        start_str = (request.args.get("start") or "").strip()
        end = _date.fromisoformat(end_str) if end_str else _date.today()
        if start_str:
            start = _date.fromisoformat(start_str)
        else:
            days_arg = int(request.args.get("days") or 60)
            days_arg = max(1, min(days_arg, 365))
            start = end - timedelta(days=days_arg)
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": f"invalid date: {exc}"}), 400
    if start > end:
        return jsonify({"ok": False, "error": "start > end"}), 400
    if (end - start).days > 1100:
        start = end - timedelta(days=1100)
    try:
        items = get_overview_history(start, end)
        return jsonify({
            "ok": True,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "count": len(items),
            "items": items,
        })
    except Exception as exc:
        logger.exception("market-overview history failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc), "items": []}), 200


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
@stock_chart_bp.route('/api/stock-chart/market-sentiment/ma-count')
def market_sentiment_ma_count():
    """MA 计数: 上一交易日 close > MA20 / MA60 / both 的股票数量 + 板块分布.

    URL: ?date=YYYY-MM-DD (默认上一交易日) &force=1 (强制重算)

    数据源: cache-aside
      1. 优先查 duckdb.ma_count_daily (0.8ms, 持久化数据)
      2. 没记录才现算 (window function on daily_qfq, ~10s) + 自动落盘

    归属: market-sentiment 命名空间 (跟风险偏好同空间), 不是 market-pulse.
    """
    from backend.repositories.market.indicator_repo import calc_ma_count_cached
    date_str = (request.args.get("date") or "").strip() or _latest_market_sentiment_trade_date_str()
    force = request.args.get("force") == "1"
    try:
        payload = calc_ma_count_cached(date_str, force=force)
        return jsonify({"ok": True, **payload})
    except Exception as exc:
        logger.exception("ma-count failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc), "tradeDate": date_str}), 200


@stock_chart_bp.route('/api/stock-chart/market-sentiment/ma-count/history')
def market_sentiment_ma_count_history():
    """MA 计数历史序列 (趋势图用, 按日期范围查).

    URL: ?start=YYYY-MM-DD (默认 end - 30d) &end=YYYY-MM-DD (默认 start + 30d)

    数据源: duckdb.ma_count_daily (持久化)
    """
    from datetime import date as _date, timedelta
    from backend.repositories.market.indicator_repo import get_ma_count_history
    end_str = (request.args.get("end") or "").strip()
    start_str = (request.args.get("start") or "").strip()
    try:
        end = _date.fromisoformat(end_str) if end_str else _date.today()
        start = _date.fromisoformat(start_str) if start_str else end - timedelta(days=30)
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": f"invalid date: {exc}"}), 400
    if start > end:
        return jsonify({"ok": False, "error": "start > end"}), 400
    # 安全上限: 365 天
    if (end - start).days > 1100:
        start = end - timedelta(days=1100)
    try:
        items = get_ma_count_history(start, end)
        return jsonify({
            "ok": True, "start": start.isoformat(), "end": end.isoformat(),
            "count": len(items), "items": items,
        })
    except Exception as exc:
        logger.exception("ma-count history failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc), "items": []}), 200


@stock_chart_bp.route('/api/stock-chart/market-pulse/index-returns')
def market_pulse_index_returns():
    """宽基指数近 N 日累计收益 (沪深300 / 中证1000).

    URL: ?days=5 (1-60, 默认 5) &force=1 (强制重算)

    数据源: cache-aside
      1. 优先查 duckdb.index_returns_daily (1.5ms, 持久化)
      2. 没记录才现算 (from index_daily_raw LAG) + 自动落盘
    """
    from backend.repositories.market.index_repo import get_index_returns_cached
    try:
        days = int(request.args.get("days") or 5)
    except (TypeError, ValueError):
        days = 5
    days = max(1, min(60, days))
    force = request.args.get("force") == "1"
    try:
        items = get_index_returns_cached(days=days, force=force)
        return jsonify({"ok": True, "days": days, "items": items})
    except Exception as exc:
        logger.exception("index-returns failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc), "days": days, "items": []}), 200


@stock_chart_bp.route('/api/stock-chart/market-pulse/index-returns/history')
def market_pulse_index_returns_history():
    """宽基指数 N 日收益历史序列 (趋势图用, 一日一条 = 沪深300 + 中证1000 各 1).

    URL: ?window=5 (1-60, 默认 5) &start=YYYY-MM-DD (默认 end - 30d) &end=YYYY-MM-DD (默认 start + 30d)

    数据源: duckdb.index_returns_daily (持久化)
    """
    from datetime import date as _date, timedelta
    from backend.repositories.market.index_repo import get_index_returns_history
    try:
        window = int(request.args.get("window") or 5)
    except (TypeError, ValueError):
        window = 5
    window = max(1, min(60, window))
    end_str = (request.args.get("end") or "").strip()
    start_str = (request.args.get("start") or "").strip()
    try:
        end = _date.fromisoformat(end_str) if end_str else _date.today()
        start = _date.fromisoformat(start_str) if start_str else end - timedelta(days=30)
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": f"invalid date: {exc}"}), 400
    if start > end:
        return jsonify({"ok": False, "error": "start > end"}), 400
    if (end - start).days > 1100:
        start = end - timedelta(days=1100)
    try:
        items = get_index_returns_history(window, start, end)
        return jsonify({
            "ok": True, "window": window, "start": start.isoformat(), "end": end.isoformat(),
            "count": len(items), "items": items,
        })
    except Exception as exc:
        logger.exception("index-returns history failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc), "items": []}), 200


@stock_chart_bp.route('/api/stock-chart/market-pulse/sector-history')
def market_pulse_sector_history():
    """市场脉搏 · 90 行业 历史快照 (按 trade_date DESC, 每日内按 change_pct DESC).

    URL: ?days=10 (1-120, 默认 10) &topN=20 (None=全量 90)

    数据源: Postgres market_pulse_sector_daily_snapshots
    """
    from backend.config.database import session_scope
    from backend.repositories.market.market_pulse_pg_repo import MarketPulseRepository
    try:
        days = int(request.args.get("days") or 10)
    except (TypeError, ValueError):
        days = 10
    days = max(1, min(days, 120))
    top_n_arg = request.args.get("topN")
    try:
        top_n = int(top_n_arg) if top_n_arg else None
    except (TypeError, ValueError):
        top_n = None
    try:
        with session_scope() as db:
            repo = MarketPulseRepository(db)
            repo.ensure_bootstrapped()
            trade_dates = repo.list_trade_dates(limit=days)
            rows = []
            for trade_date in trade_dates:
                items = repo.get_trade_day_rows(trade_date)
                if top_n is not None:
                    items = items[:top_n]
                rows.append({"tradeDate": trade_date, "items": items})
        return jsonify({
            "ok": True,
            "days": days,
            "topN": top_n,
            "count": len(rows),
            "items": rows,
        })
    except Exception as exc:
        logger.exception("sector-history failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc), "items": []}), 200


@stock_chart_bp.route('/api/stock-chart/market-pulse/sector-daily')
def market_pulse_sector_daily():
    """市场脉搏 · 90 行业 单日 Top/Bottom N (供前端 rotation 卡片用).

    URL: ?date=YYYY-MM-DD (默认今天) &topN=10 (1-90, 默认 10)

    数据源: Postgres market_pulse_sector_daily_snapshots
    """
    from datetime import date as _date
    from backend.config.database import session_scope
    from backend.repositories.market.market_pulse_pg_repo import MarketPulseRepository
    from backend.utils.trading_day import resolve_fund_flow_read_trade_date
    try:
        top_n = int(request.args.get("topN") or 10)
    except (TypeError, ValueError):
        top_n = 10
    top_n = max(1, min(top_n, 90))
    date_str = (request.args.get("date") or "").strip()
    try:
        requested_date = _date.fromisoformat(date_str) if date_str else resolve_fund_flow_read_trade_date()
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": f"invalid date: {exc}"}), 400
    try:
        with session_scope() as db:
            repo = MarketPulseRepository(db)
            repo.ensure_bootstrapped()
            trade_date = repo.latest_trade_date(end=requested_date) or repo.latest_trade_date()
            items = repo.get_trade_day_rows(trade_date) if trade_date else []
        payload = {
            "tradeDate": trade_date.isoformat() if trade_date else None,
            "topN": top_n,
            "top": items[:top_n],
            "bottom": list(reversed(items[-min(top_n, len(items)):])),
            "count": len(items),
        }
        return jsonify({"ok": True, **payload})
    except Exception as exc:
        logger.exception("sector-daily failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500


@stock_chart_bp.route('/api/stock-chart/market-sentiment/sector-breadth')
def market_sentiment_sector_breadth():
    """板块扩散: 上涨行业数 / 下跌 / 平盘 / 有效行业数 + advance_pct.

    URL: ?date=YYYY-MM-DD (默认今天)
         &days=N (1-365, 默认 0=单日模式; >0 走区间模式)

    数据源: duckdb.market_pulse_sector_breadth_daily
            (由 ths_industry_fund_flow_daily 聚合, 工作日 17:15 收盘后算)

    cache-aside: 优先查表, 没记录自动算 + 落盘 (依赖 ths_industry_fund_flow_daily 当天数据齐)

    归属: market-sentiment 命名空间 (跟 ma-count / risk-appetite / limit-emotion-summary 同空间),
    不是 market-pulse (数据来源是 ths 90 行业, 跟 PulseStats 的 6 张大盘宽度卡不同维度).
    """
    from datetime import date as _date
    from backend.repositories.market.sector_breadth_repo import (
        calc_sector_breadth_cached, get_sector_breadth_history,
    )
    date_str = (request.args.get("date") or "").strip()
    try:
        days = int(request.args.get("days") or 0)
    except (TypeError, ValueError):
        days = 0
    days = max(0, min(days, 365))
    try:
        if date_str:
            td = _date.fromisoformat(date_str)
        else:
            td = _date.fromisoformat(_latest_market_sentiment_trade_date_str())
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": f"invalid date: {exc}"}), 400

    if days > 0:
        # 区间模式
        end_d = td
        start_d = _date.fromordinal(end_d.toordinal() - days)  # 简单减天数
        items = get_sector_breadth_history(start_d.isoformat(), end_d.isoformat(), limit=days)
        return jsonify({
            "ok": True,
            "start": start_d.isoformat(),
            "end": end_d.isoformat(),
            "days": days,
            "count": len(items),
            "items": items,
        })
    # 单日模式: cache-aside
    try:
        payload = calc_sector_breadth_cached(td)
    except Exception as exc:
        logger.exception("sector-breadth cache-aside failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500
    if payload is None:
        return jsonify({
            "ok": False,
            "error": f"no ths_industry_fund_flow data for {td.isoformat()}",
            "tradeDate": td.isoformat(),
        }), 404
    return jsonify({"ok": True, **payload})


@stock_chart_bp.route('/api/stock-chart/market-sentiment/sector-breadth/history')
def market_sentiment_sector_breadth_history():
    """板块扩散历史序列 (sparkline 用, 按日期范围查).

    URL: ?start=YYYY-MM-DD (默认 end - 30d) &end=YYYY-MM-DD (默认 start + 30d)

    数据源: duckdb.market_pulse_sector_breadth_daily (持久化)
    """
    from datetime import date as _date, timedelta
    from backend.repositories.market.sector_breadth_repo import get_sector_breadth_history
    end_str = (request.args.get("end") or "").strip()
    start_str = (request.args.get("start") or "").strip()
    try:
        end = _date.fromisoformat(end_str) if end_str else _date.today()
        start = _date.fromisoformat(start_str) if start_str else end - timedelta(days=30)
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": f"invalid date: {exc}"}), 400
    if start > end:
        return jsonify({"ok": False, "error": "start > end"}), 400
    # 安全上限: 365 天
    if (end - start).days > 1100:
        start = end - timedelta(days=1100)
    try:
        items = get_sector_breadth_history(start, end)
        return jsonify({
            "ok": True, "start": start.isoformat(), "end": end.isoformat(),
            "count": len(items), "items": items,
        })
    except Exception as exc:
        logger.exception("sector-breadth history failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc), "items": []}), 200


@stock_chart_bp.route('/api/stock-chart/market-sentiment/risk-appetite')
def market_sentiment_risk_appetite():
    """风险偏好: 沪深300 20日累计收益 - (511010 + 511090) / 2 加权国债 ETF 20日收益.

    URL: ?date=YYYY-MM-DD (默认上一交易日) &force=1 (强制重算)

    数据源: cache-aside
      1. 优先查 duckdb.risk_appetite_daily (0.8ms, 持久化)
      2. 没记录才现算 (from daily_qfq LAG) + 自动落盘
    """
    from datetime import date as _date
    from backend.repositories.market.risk_appetite_repo import calc_risk_appetite_cached
    date_str = (request.args.get("date") or "").strip()
    force = request.args.get("force") in ("1", "true", "yes")
    if not date_str:
        date_str = _latest_market_sentiment_trade_date_str()
    try:
        payload = calc_risk_appetite_cached(date_str, force=force)
        return jsonify({"ok": True, **payload})
    except Exception as exc:
        logger.exception("risk-appetite failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc), "tradeDate": date_str}), 200


@stock_chart_bp.route('/api/stock-chart/market-sentiment/risk-appetite/history')
def market_sentiment_risk_appetite_history():
    """风险偏好历史序列 (sparkline 用, 按日期范围查).

    URL: ?start=YYYY-MM-DD (默认 end - 30d) &end=YYYY-MM-DD (默认 start + 30d)

    数据源: duckdb.risk_appetite_daily (持久化)
    """
    from datetime import date as _date, timedelta
    from backend.repositories.market.risk_appetite_repo import get_risk_appetite_history
    end_str = (request.args.get("end") or "").strip()
    start_str = (request.args.get("start") or "").strip()
    try:
        end = _date.fromisoformat(end_str) if end_str else _date.today()
        start = _date.fromisoformat(start_str) if start_str else end - timedelta(days=30)
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": f"invalid date: {exc}"}), 400
    if start > end:
        return jsonify({"ok": False, "error": "start > end"}), 400
    if (end - start).days > 1100:
        start = end - timedelta(days=1100)
    try:
        items = get_risk_appetite_history(start, end)
        return jsonify({
            "ok": True, "start": start.isoformat(), "end": end.isoformat(),
            "count": len(items), "items": items,
        })
    except Exception as exc:
        logger.exception("risk-appetite history failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc), "items": []}), 200


@stock_chart_bp.route('/api/stock-chart/market-sentiment/limit-emotion-summary')
def market_sentiment_limit_emotion_summary():
    """涨跌停情绪综合分 (短线情绪): 涨跌停比 + 炸板率 + 昨日涨停收益 → composite.

    URL: ?date=YYYY-MM-DD (默认上一交易日) &force=1 (强制重算)

    数据源: cache-aside
      1. 优先查 duckdb.limit_emotion_summary_daily (持久化)
      2. 没记录才现算 (复用 limit_repo.get_today_limit_snapshot) + 自动落盘

    公式 (v1.1, 2026-06-18):
      - 所有子项改用历史分位 (percentile), 替代固定公式
      - up_down_score       = percentile(涨跌停比)                        ∈ [0, 100]
      - break_board_score   = 100 - percentile(炸板率)                    ∈ [0, 100]  (反向)
      - yesterday_return_score = percentile(昨日涨停收益)                  ∈ [0, 100]
      - composite = percentile(0.4*A + 0.3*B + 0.3*C)                   ∈ [0, 100]
      - level: hot/active/normal/weak/ice
    """
    from datetime import date as _date
    from backend.repositories.market.limit_repo import calc_limit_emotion_summary_cached
    date_str = (request.args.get("date") or "").strip()
    force = request.args.get("force") in ("1", "true", "yes")
    if not date_str:
        date_str = _latest_market_sentiment_trade_date_str()
    try:
        payload = calc_limit_emotion_summary_cached(date_str, force=force)
        return jsonify({"ok": True, **payload})
    except Exception as exc:
        logger.exception("limit-emotion-summary failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc), "tradeDate": date_str}), 200


@stock_chart_bp.route('/api/stock-chart/market-sentiment/limit-emotion-summary/history')
def market_sentiment_limit_emotion_summary_history():
    """涨跌停情绪综合分历史序列 (sparkline 用).

    URL: ?start=YYYY-MM-DD (默认 end - 30d) &end=YYYY-MM-DD (默认 start + 30d)

    数据源: duckdb.limit_emotion_summary_daily (持久化)
    """
    from datetime import date as _date, timedelta
    from backend.repositories.market.limit_repo import get_limit_emotion_summary_history
    end_str = (request.args.get("end") or "").strip()
    start_str = (request.args.get("start") or "").strip()
    try:
        end = _date.fromisoformat(end_str) if end_str else _date.today()
        start = _date.fromisoformat(start_str) if start_str else end - timedelta(days=30)
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": f"invalid date: {exc}"}), 400
    if start > end:
        return jsonify({"ok": False, "error": "start > end"}), 400
    if (end - start).days > 1100:
        start = end - timedelta(days=1100)
    try:
        items = get_limit_emotion_summary_history(start, end)
        return jsonify({
            "ok": True, "start": start.isoformat(), "end": end.isoformat(),
            "count": len(items), "items": items,
        })
    except Exception as exc:
        logger.exception("limit-emotion-summary history failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc), "items": []}), 200


@stock_chart_bp.route('/api/stock-chart/market-sentiment/volatility-sentiment')
def market_sentiment_volatility_sentiment():
    """波动率情绪 (情绪分项 ⑤): 沪深300 20 日年化波动率 → 1 年历史分位 → 反向情绪得分.

    URL: ?date=YYYY-MM-DD (默认上一交易日) &force=1 (强制重算)

    公式 (v1.0):
      realized_vol_20d = std(近 20 日日收益率) × √252 × 100  (%, 年化)
      percentile_1y    = rank(近 252 个交易日的 vol, 含等于) / 252  ∈ [0, 1]
      sentiment_score  = (1 - percentile_1y) × 100  ∈ [0, 100]   (反向, 高分=情绪好)

    数据源: cache-aside
      1. 优先查 duckdb.volatility_sentiment_daily (持久化)
      2. 没记录才现算 (从 index_daily_raw LAG) + 自动落盘

    归属: market-sentiment 命名空间 (跟 ma-count / risk-appetite / limit-emotion-summary 同空间).
    """
    from datetime import date as _date
    from backend.repositories.market.volatility_sentiment_repo import (
        calc_volatility_sentiment_cached,
    )
    date_str = (request.args.get("date") or "").strip()
    force = request.args.get("force") in ("1", "true", "yes")
    if not date_str:
        date_str = _latest_market_sentiment_trade_date_str()
    try:
        payload = calc_volatility_sentiment_cached(date_str, force=force)
        if payload is None:
            return jsonify({
                "ok": False,
                "error": f"no index data / not enough history for {date_str}",
                "tradeDate": date_str,
            }), 200
        return jsonify({"ok": True, **payload})
    except Exception as exc:
        logger.exception("volatility-sentiment failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc), "tradeDate": date_str}), 200


@stock_chart_bp.route('/api/stock-chart/market-sentiment/volatility-sentiment/history')
def market_sentiment_volatility_sentiment_history():
    """波动率情绪历史序列 (sparkline 用, 按日期范围查).

    URL: ?start=YYYY-MM-DD (默认 end - 30d) &end=YYYY-MM-DD (默认 start + 30d)

    数据源: duckdb.volatility_sentiment_daily (持久化)
    """
    from datetime import date as _date, timedelta
    from backend.repositories.market.volatility_sentiment_repo import (
        get_volatility_sentiment_history,
    )
    end_str = (request.args.get("end") or "").strip()
    start_str = (request.args.get("start") or "").strip()
    try:
        end = _date.fromisoformat(end_str) if end_str else _date.today()
        start = _date.fromisoformat(start_str) if start_str else end - timedelta(days=30)
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": f"invalid date: {exc}"}), 400
    if start > end:
        return jsonify({"ok": False, "error": "start > end"}), 400
    if (end - start).days > 1100:
        start = end - timedelta(days=1100)
    try:
        items = get_volatility_sentiment_history(start, end)
        return jsonify({
            "ok": True, "start": start.isoformat(), "end": end.isoformat(),
            "count": len(items), "items": items,
        })
    except Exception as exc:
        logger.exception("volatility-sentiment history failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc), "items": []}), 200


# ---------------------------------------------------------------------------
# 成交活跃度 (Turnover Activity)
# ---------------------------------------------------------------------------

@stock_chart_bp.route('/api/stock-chart/market-sentiment/turnover-activity')
def market_sentiment_turnover_activity():
    """成交活跃度: 今日全市场成交额 / 过去 20 日平均成交额.

    URL: ?date=YYYY-MM-DD (默认上一个交易日) &force=1

    数据源:
      1. 优先查 duckdb.turnover_activity_daily (持久化)
      2. 没记录则从 duckdb.daily_raw 中读取 999999 + 399001 成交额求和现算 + 自动落盘
    """
    from datetime import date as _date
    from backend.repositories.market.turnover_activity_repo import (
        calc_turnover_activity_cached,
    )
    date_str = (request.args.get("date") or "").strip()
    if not date_str:
        date_str = _latest_market_sentiment_trade_date_str()
    try:
        _date.fromisoformat(date_str)
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": f"invalid date: {exc}"}), 400
    force = bool(request.args.get("force"))
    try:
        payload = calc_turnover_activity_cached(date_str, force=force)
        if payload is None:
            return jsonify({"ok": True, **{"tradeDate": date_str, "totalAmount": None, "avg20dAmount": None, "ratio": None, "elapsedMs": None, "source": "no_data"}})
        return jsonify({"ok": True, **payload})
    except Exception as exc:
        logger.exception("turnover-activity failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500


@stock_chart_bp.route('/api/stock-chart/market-sentiment/turnover-activity/history')
def market_sentiment_turnover_activity_history():
    """成交活跃度历史序列 (sparkline 用).

    URL: ?start=YYYY-MM-DD (默认 end - 30d) &end=YYYY-MM-DD (默认 start + 30d)

    数据源: duckdb.turnover_activity_daily (持久化)
    """
    from datetime import date as _date, timedelta
    from backend.repositories.market.turnover_activity_repo import (
        get_turnover_activity_history,
    )
    end_str = (request.args.get("end") or "").strip()
    start_str = (request.args.get("start") or "").strip()
    try:
        end = _date.fromisoformat(end_str) if end_str else _date.today()
        start = _date.fromisoformat(start_str) if start_str else end - timedelta(days=30)
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": f"invalid date: {exc}"}), 400
    if start > end:
        return jsonify({"ok": False, "error": "start > end"}), 400
    if (end - start).days > 1100:
        start = end - timedelta(days=1100)
    try:
        items = get_turnover_activity_history(start, end)
        return jsonify({
            "ok": True, "start": start.isoformat(), "end": end.isoformat(),
            "count": len(items), "items": items,
        })
    except Exception as exc:
        logger.exception("turnover-activity history failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc), "items": []}), 200


@stock_chart_bp.route('/api/stock-chart/market-sentiment/style-risk-appetite')
def market_sentiment_style_risk_appetite():
    """风格风险偏好: 中证1000 近5日收益 - 沪深300 近5日收益.

    URL: ?date=YYYY-MM-DD (默认上一交易日) &force=1 (强制重算)

    数据源: cache-aside
      1. 优先查 duckdb.style_risk_appetite_daily
      2. 没记录才现算 (读 index_returns_daily) + 自动落盘

    说明: spread > 0 = 小盘强 (风险偏好积极), spread < 0 = 大盘强 (避险).
    """
    from datetime import date as _date
    from backend.repositories.market.style_risk_appetite_repo import (
        calc_style_risk_appetite_cached,
    )
    date_str = (request.args.get("date") or "").strip()
    force = request.args.get("force") in ("1", "true", "yes")
    if not date_str:
        date_str = _latest_market_sentiment_trade_date_str()
    try:
        payload = calc_style_risk_appetite_cached(date_str, force=force)
        if payload is None:
            return jsonify({
                "ok": False,
                "error": f"no index_returns_daily data for {date_str}",
                "tradeDate": date_str,
            }), 404
        return jsonify({"ok": True, **payload})
    except Exception as exc:
        logger.exception("style-risk-appetite failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc), "tradeDate": date_str}), 200


@stock_chart_bp.route('/api/stock-chart/market-sentiment/style-risk-appetite/history')
def market_sentiment_style_risk_appetite_history():
    """风格风险偏好历史序列 (sparkline 用, 按日期范围查).

    URL: ?start=YYYY-MM-DD (默认 end - 30d) &end=YYYY-MM-DD (默认 start + 30d)

    数据源: duckdb.style_risk_appetite_daily (持久化)
    """
    from datetime import date as _date, timedelta
    from backend.repositories.market.style_risk_appetite_repo import (
        get_style_risk_appetite_history,
    )
    end_str = (request.args.get("end") or "").strip()
    start_str = (request.args.get("start") or "").strip()
    try:
        end = _date.fromisoformat(end_str) if end_str else _date.today()
        start = _date.fromisoformat(start_str) if start_str else end - timedelta(days=30)
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": f"invalid date: {exc}"}), 400
    if start > end:
        return jsonify({"ok": False, "error": "start > end"}), 400
    if (end - start).days > 1100:
        start = end - timedelta(days=1100)
    try:
        items = get_style_risk_appetite_history(start, end)
        return jsonify({
            "ok": True, "start": start.isoformat(), "end": end.isoformat(),
            "count": len(items), "items": items,
        })
    except Exception as exc:
        logger.exception("style-risk-appetite history failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc), "items": []}), 200


@stock_chart_bp.route('/api/stock-chart/market-sentiment/profit-effect')
def market_sentiment_profit_effect():
    """赚钱效应: 60%×近5日上涨占比 + 40%×(100-60日新低占比).

    URL: ?date=YYYY-MM-DD (默认上一交易日) &force=1 (强制重算)

    数据源: cache-aside
      1. 优先查 duckdb.profit_effect_daily
      2. 没记录才现算 (读 ma_count_daily) + 自动落盘
    """
    from datetime import date as _date
    from backend.repositories.market.profit_effect_repo import (
        calc_profit_effect_cached,
    )
    date_str = (request.args.get("date") or "").strip()
    force = request.args.get("force") in ("1", "true", "yes")
    if not date_str:
        date_str = _latest_market_sentiment_trade_date_str()
    try:
        payload = calc_profit_effect_cached(date_str, force=force)
        if payload is None:
            return jsonify({
                "ok": False,
                "error": f"no ma_count_daily data for {date_str}",
                "tradeDate": date_str,
            }), 404
        return jsonify({"ok": True, **payload})
    except Exception as exc:
        logger.exception("profit-effect failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc), "tradeDate": date_str}), 200


@stock_chart_bp.route('/api/stock-chart/market-sentiment/profit-effect/history')
def market_sentiment_profit_effect_history():
    """赚钱效应历史序列 (sparkline 用, 按日期范围查).

    URL: ?start=YYYY-MM-DD (默认 end - 30d) &end=YYYY-MM-DD (默认 start + 30d)
    """
    from datetime import date as _date, timedelta
    from backend.repositories.market.profit_effect_repo import get_profit_effect_history
    end_str = (request.args.get("end") or "").strip()
    start_str = (request.args.get("start") or "").strip()
    try:
        end = _date.fromisoformat(end_str) if end_str else _date.today()
        start = _date.fromisoformat(start_str) if start_str else end - timedelta(days=30)
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": f"invalid date: {exc}"}), 400
    if start > end:
        return jsonify({"ok": False, "error": "start > end"}), 400
    if (end - start).days > 1100:
        start = end - timedelta(days=1100)
    try:
        items = get_profit_effect_history(start, end)
        return jsonify({
            "ok": True, "start": start.isoformat(), "end": end.isoformat(),
            "count": len(items), "items": items,
        })
    except Exception as exc:
        logger.exception("profit-effect history failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc), "items": []}), 200


@stock_chart_bp.route('/api/stock-chart/market-sentiment/index')
def market_sentiment_index():
    """市场情绪指数 composite (9 张卡加权合成).

    URL: ?date=YYYY-MM-DD (默认上一交易日) &force=1 (强制重算)

    权重: vol 15% + turnover 15% + breadth 15% + limit_emotion 15% +
          price_strength 10% + risk_appetite 10% + profit_effect 10% +
          sector_breadth 5% + style_risk 5% = 100%

    数据源: cache-aside
      1. 优先查 duckdb.market_sentiment_index_daily
      2. 没记录才现算 (从 8 张 sub-card *_daily 拿 component) + 自动落盘
    """
    from datetime import date as _date
    from backend.repositories.market.market_sentiment_index_repo import (
        calc_market_sentiment_index_cached,
    )
    date_str = (request.args.get("date") or "").strip()
    force = request.args.get("force") in ("1", "true", "yes")
    if not date_str:
        date_str = _latest_market_sentiment_trade_date_str()
    try:
        payload = calc_market_sentiment_index_cached(date_str, force=force)
        if payload is None:
            return jsonify({
                "ok": False,
                "error": f"no sub-card data for {date_str}",
                "tradeDate": date_str,
            }), 404
        return jsonify({"ok": True, **payload})
    except Exception as exc:
        logger.exception("market-sentiment-index failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc), "tradeDate": date_str}), 200


@stock_chart_bp.route('/api/stock-chart/market-sentiment/index/history')
def market_sentiment_index_history():
    """市场情绪指数历史序列 (顶部大卡 sparkline 用).

    URL: ?start=YYYY-MM-DD (默认 end - 30d) &end=YYYY-MM-DD (默认 start + 30d)
    """
    from datetime import date as _date, timedelta
    from backend.repositories.market.market_sentiment_index_repo import (
        get_market_sentiment_index_history,
    )
    end_str = (request.args.get("end") or "").strip()
    start_str = (request.args.get("start") or "").strip()
    try:
        end = _date.fromisoformat(end_str) if end_str else _date.today()
        start = _date.fromisoformat(start_str) if start_str else end - timedelta(days=30)
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": f"invalid date: {exc}"}), 400
    if start > end:
        return jsonify({"ok": False, "error": "start > end"}), 400
    if (end - start).days > 1100:
        start = end - timedelta(days=1100)
    try:
        items = get_market_sentiment_index_history(start, end)
        return jsonify({
            "ok": True, "start": start.isoformat(), "end": end.isoformat(),
            "count": len(items), "items": items,
        })
    except Exception as exc:
        logger.exception("market-sentiment-index history failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc), "items": []}), 200


@stock_chart_bp.route('/api/stock-chart/index/daily')
def index_daily_history():
    """单只宽基指数日线历史 (Market Sentiment 顶部卡 / POC 叠加用).

    URL: ?code=000001 (必填, 兼容 'sh000001' / 'sz399001')
         &start=YYYY-MM-DD (默认 end-1095d)
         &end=YYYY-MM-DD   (默认 today)

    返回 items 含 tradeDate / close / amount (成交额, 元).
    注: 成交额沿用 duckdb.index_daily_raw.amount 原始单位 (元), 不在端点层做单位换算,
        让前端按需要 (/1e8 转亿) 处理.

    数据源: duckdb.index_daily_raw → index_repo.get_index_daily
    """
    from datetime import date as _date, timedelta
    from backend.repositories.market.index_repo import get_index_daily
    code = _normalize_index_code(request.args.get('code', ''))
    if not code:
        return jsonify({"ok": False, "error": "code required"}), 400
    end_str = (request.args.get("end") or "").strip()
    start_str = (request.args.get("start") or "").strip()
    try:
        end = _date.fromisoformat(end_str) if end_str else _date.today()
        start = _date.fromisoformat(start_str) if start_str else end - timedelta(days=1095)
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": f"invalid date: {exc}"}), 400
    if start > end:
        return jsonify({"ok": False, "error": "start > end"}), 400
    # get_index_daily 上限 1500, 多取 30 天冗余防边界 (3 年窗口 = ~770 天, 留 2x buffer)
    days = max(1, min(1500, (end - start).days + 30))
    # duckdb.index_daily_raw 用 'sh000300' / 'sz399001' 这种带前缀 code (避免与 A股 000300 撞码)
    # 客户端传 6 位 code ('000001'), 这里按首位加前缀. 已是前缀的保持不变.
    full_code = code if code.startswith(('sh', 'sz')) else (
        ('sh' + code) if code[:1] in ('0', '6', '9') else ('sz' + code)
    )
    try:
        rows = get_index_daily(full_code, days=days)
        items: list[dict] = []
        for r in rows:
            td = r["trade_date"]
            if isinstance(td, str):
                td_d = _date.fromisoformat(td)
            else:
                td_d = td
            if start <= td_d <= end:
                items.append({
                    "tradeDate": td_d.isoformat(),
                    "close": float(r["close"]),
                    "amount": float(r.get("amount") or 0),
                })
        return jsonify({
            "ok": True, "code": code,
            "name": _INDEX_CODE_TO_NAME.get(code, code),
            "start": start.isoformat(), "end": end.isoformat(),
            "count": len(items), "items": items,
        })
    except Exception as exc:
        logger.exception("index daily history failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc), "items": []}), 200


@stock_chart_bp.route('/api/stock-chart/market-pulse/strong')
def market_pulse_strong():
    """强势板块: Postgres 日快照派生的行业涨跌幅榜. URL: ?topN=10&refresh=1"""
    from backend.services.stock.market_pulse_service import build_strong_sectors
    try:
        top_n = int(request.args.get("topN") or 10)
    except (TypeError, ValueError):
        top_n = 10
    try:
        return jsonify(build_strong_sectors(top_n=top_n, force_refresh=request.args.get("refresh") == "1"))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "top": [], "bottom": []}), 200


@stock_chart_bp.route('/api/stock-chart/market-pulse/capital-flow')
def market_pulse_capital_flow():
    """行业主力净流入: Postgres 日快照派生. URL: ?topN=20&refresh=1"""
    from backend.services.stock.market_pulse_service import build_capital_flow
    try:
        top_n = int(request.args.get("topN") or 20)
    except (TypeError, ValueError):
        top_n = 20
    try:
        return jsonify(build_capital_flow(top_n=top_n, force_refresh=request.args.get("refresh") == "1"))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "inflow": [], "outflow": []}), 200


@stock_chart_bp.route('/api/stock-chart/market-pulse/rotation')
def market_pulse_rotation():
    """行业轮动: 读 Postgres 交易日日快照.

    URL: ?days=10&topN=10&refresh=1
        refresh=1 强制刷新今日快照 (非交易日仍回退上一交易日, 不写非交易日).
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
        return jsonify(build_industry_rotation(days=days, top_n=top_n, force_refresh=False))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "rows": [], "dates": []}), 200


@stock_chart_bp.route('/api/stock-chart/market-pulse/all')
def market_pulse_all():
    """一次拿三块, 行情页首屏用. URL: ?days=30&topN=10"""
    from backend.services.stock.market_pulse_service import build_market_pulse
    try:
        days = int(request.args.get("days") or 10)
    except (TypeError, ValueError):
        days = 10
    try:
        top_n = int(request.args.get("topN") or 10)
    except (TypeError, ValueError):
        top_n = 10
    try:
        return jsonify(
            build_market_pulse(
                days=days,
                top_n=top_n,
                force_refresh=request.args.get("refresh") == "1",
            )
        )
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


@stock_chart_bp.route('/api/stock-chart/market-pulse/industry-compare')
def market_pulse_industry_compare():
    """多行业跨日净流 / 排名对比.

    URL: ?industries=半导体,软件服务&days=120&end=2026-06-23
    URL: ?industry=半导体&industry=软件服务&days=120
    """
    from backend.services.stock.market_pulse_service import build_industry_compare

    raw_names = []
    industries_arg = (request.args.get("industries") or "").strip()
    if industries_arg:
        raw_names.extend(part.strip() for part in industries_arg.split(","))
    raw_names.extend((item or "").strip() for item in request.args.getlist("industry"))
    names = [item for item in raw_names if item]
    if not names:
        return jsonify({"ok": False, "error": "industry or industries is required", "industries": []}), 400

    try:
        days = int(request.args.get("days") or 120)
    except (TypeError, ValueError):
        days = 120
    days = max(1, min(days, 365))
    end = (request.args.get("end") or "").strip() or None
    try:
        return jsonify(build_industry_compare(names, days=days, end=end))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "industries": [], "dates": []}), 200


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
# 维护前请先看:
# F:\dev-repo\mp4-to-word-new\design\backend\industry-concept-fund-flow-postgres-migration.md
# 如果改同花顺行业资金流的结构、历史接口、抓取写库方式或前端契约，先更新 design 文档；
# 改完代码后也要同步回写 design 文档。
@stock_chart_bp.route('/api/stock-chart/ths-industry/fund-flow')
def ths_industry_fund_flow():
    """同花顺全行业主力资金动向.

    URL: ?refresh=1 (强制重爬) &top=10 (只返 top N, 按净额 desc)

    路由:
      GET /api/stock-chart/ths-industry/fund-flow           读 Postgres 最新交易日快照
      GET /api/stock-chart/ths-industry/fund-flow?refresh=1 强制重爬 + 写 Postgres
      GET /api/stock-chart/ths-industry/fund-flow?top=10    读最新快照, 截前 10
    """
    refresh = request.args.get("refresh") == "1"
    top_param = (request.args.get("top") or "").strip()
    try:
        top = int(top_param) if top_param else None
    except (TypeError, ValueError):
        top = None
    if top is not None:
        top = max(1, min(200, top))

    try:
        from backend.config.database import session_scope
        from backend.services.stock.f10.ths_fund_flow_service import ThsIndustryFundFlowService

        with session_scope() as db:
            payload = ThsIndustryFundFlowService(db).get_industry_fund_flow(refresh=refresh, top=top)
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
    try:
        from backend.config.database import session_scope
        from backend.services.stock.f10.ths_fund_flow_service import ThsIndustryFundFlowService

        with session_scope() as db:
            payload = ThsIndustryFundFlowService(db).refresh_industry_fund_flow()
        return jsonify(payload)
    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
            "rows": [],
            "rowCount": 0,
        }), 200


@stock_chart_bp.route('/api/stock-chart/ths-industry/fund-flow/history')
def ths_industry_fund_flow_history():
    """列出 / 读取 交易日历史快照.

    URL: GET /api/stock-chart/ths-industry/fund-flow/history
    URL: GET /api/stock-chart/ths-industry/fund-flow/history?date=2026-06-08
    """
    date_param = (request.args.get("date") or "").strip()
    from backend.config.database import session_scope
    from backend.services.stock.f10.ths_fund_flow_service import ThsIndustryFundFlowService

    with session_scope() as db:
        service = ThsIndustryFundFlowService(db)
        if date_param:
            payload = service.read_history(date_param)
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
            "dates": service.list_history_dates(),
        })


# ---------------------------------------------------------------------------
# 同花顺 90 行业资金流 · Postgres 历史序列
# 数据源: app.sector_fund_flow_daily_snapshots / app.sector_fund_flow_capture_batches
# 跟原 /fund-flow 共用同一套快照, 这里只是提供 top/bottom 和跨日序列能力
# ---------------------------------------------------------------------------

@stock_chart_bp.route('/api/stock-chart/ths-industry/fund-flow/db-history')
def ths_industry_fund_flow_db_history():
    """读 Postgres 的近 N 天 历史序列.

    URL: ?days=10 (1-120, 默认 10) &topN=20 (None=全量 90) &date=YYYY-MM-DD
         (date 优先: 给定 date 时, 只返该日的 top/bottom)
    """
    date_str = (request.args.get("date") or "").strip()
    try:
        top_n_arg = request.args.get("topN")
        top_n = int(top_n_arg) if top_n_arg else 10
    except (TypeError, ValueError):
        top_n = 10
    top_n = max(1, min(top_n, 90))

    try:
        from backend.config.database import session_scope
        from backend.repositories.market.ths_industry_fund_flow_repo import ThsIndustryFundFlowRepository

        with session_scope() as db:
            repo = ThsIndustryFundFlowRepository(db)
            repo.ensure_bootstrapped()
            if date_str:
                payload = repo.get_fund_flow_daily_topn(date_str, top_n=top_n)
                return jsonify({"ok": True, **payload})
            try:
                days = int(request.args.get("days") or 10)
            except (TypeError, ValueError):
                days = 10
            days = max(1, min(days, 120))
            rows = repo.get_fund_flow_history(days=days, top_n=top_n)
            return jsonify({
                "ok": True,
                "days": days,
                "topN": top_n,
                "count": len(rows),
                "items": rows,
            })
    except Exception as exc:
        logger.exception("ths-industry fund-flow db-history failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc), "items": []}), 200


@stock_chart_bp.route('/api/stock-chart/ths-industry/fund-flow/industry-series')
def ths_industry_fund_flow_industry_series():
    """单行业跨日资金流序列.

    URL: ?industry=半导体 (URL encode 即可) &days=30 (1-365, 默认 30) &end=YYYY-MM-DD
    """
    industry = (request.args.get("industry") or "").strip()
    if not industry:
        # 没传 industry: 列所有行业, 给前端"行业选择器"用
        try:
            days = int(request.args.get("days") or 30)
        except (TypeError, ValueError):
            days = 30
        days = max(1, min(days, 365))
        try:
            from backend.config.database import session_scope
            from backend.repositories.market.ths_industry_fund_flow_repo import ThsIndustryFundFlowRepository

            with session_scope() as db:
                repo = ThsIndustryFundFlowRepository(db)
                repo.ensure_bootstrapped()
                items = repo.list_industries_with_data(days=days)
                return jsonify({
                    "ok": True,
                    "days": days,
                    "count": len(items),
                    "items": items,
                })
        except Exception as exc:
            logger.exception("industry list failed: %s", exc)
            return jsonify({"ok": False, "error": str(exc), "items": []}), 200
    try:
        days = int(request.args.get("days") or 30)
    except (TypeError, ValueError):
        days = 30
    days = max(1, min(days, 365))
    end_str = (request.args.get("end") or "").strip()
    try:
        from backend.config.database import session_scope
        from backend.repositories.market.ths_industry_fund_flow_repo import ThsIndustryFundFlowRepository

        with session_scope() as db:
            repo = ThsIndustryFundFlowRepository(db)
            repo.ensure_bootstrapped()
            rows = repo.get_fund_flow_for_industry(industry, days=days, end=end_str or None)
            return jsonify({
                "ok": True,
                "industry": industry,
                "days": days,
                "count": len(rows),
                "items": rows,
            })
    except Exception as exc:
        logger.exception("industry-series failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc), "items": []}), 200


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


@stock_chart_bp.route('/api/stock-chart/style-sectors/<string:name>/constituents', methods=['GET'])
def style_sector_constituents(name: str):
    """单个 style 板块的成分股 codes + 轻量实时行情 (腾讯快照, 30s 缓存).

    用途: Market Pulse 风格板块热力图点击 cell -> 弹 drawer 展示成分股 list.

    返回::
        {
          "ok": true,
          "name": "百元股",
          "codes": ["600519", "300750", ...],
          "constituents": [
            {
              "code": "600519",
              "name": "贵州茅台",
              "last_price": 1234.56,
              "pre_close_price": 1230.00,
              "change_pct": 0.37,
              "change_amount": 4.56,
              "circulating_market_cap": 1550000000000,
              "turnover_rate": 0.12,
              "valid": true
            },
            ...
          ],
          "fetched_at": "2026-06-12T15:35:00"
        }

    行情缺失的 code: 仍然出现在 ``codes`` 里, 但 ``constituents`` 里 ``valid=false`` (前端可灰色显示).
    """
    from backend.services.stock.style_sector_service import (
        STYLE_SECTOR_NAMES,
        get_style_sector,
    )
    from backend.adapters.market.tencent import fetch_tencent_snapshots
    from backend.services.stock.stock_universe_service import list_sectors_by_category
    from backend.services.stock.style_sector_service import STYLES_CATEGORY_RAW

    if name not in STYLE_SECTOR_NAMES:
        return jsonify({"ok": False, "error": f"unknown style: {name}"}), 404

    # 1) codes (从 sectors_styles_4.json 拿)
    try:
        item = get_style_sector(name) or {}
    except Exception:
        item = {}

    codes: list[str] = []
    for s in list_sectors_by_category(STYLES_CATEGORY_RAW):
        if s.get("name") == name:
            codes = list(s.get("stock_codes") or [])
            break

    # 2) 实时行情 (腾讯 qt.gtimg.cn 批量快照, 30s 缓存)
    #    snapshot 里直接带 name, 不用额外查
    quotes: dict[str, dict] = {}
    if codes:
        try:
            quotes = fetch_tencent_snapshots(codes) or {}
        except Exception:
            quotes = {}

    # 3) 拼 constituents list
    #    **code 去除 sz/sh/bj 前缀** (前端显示 6 位 code, 跟其他页面一致)
    #    **实时计算** 振幅 / 成交额 / 流通股 / 换手率 (tencent 字段对不上, 自己算)
    constituents: list[dict] = []
    for raw in codes:
        q = quotes.get(raw) or {}
        # 去前缀: sz000048 -> 000048
        bare = raw[2:] if raw[:2] in ("sh", "sz", "bj") else raw
        last = q.get("last_price")
        pre = q.get("pre_close_price")
        # 涨跌额 / 涨跌幅: 优先用 quote 自带, 否则现价算
        chg_amt = q.get("change_amount")
        chg_pct = q.get("change_pct")
        try:
            if chg_amt is None and last not in (None, 0, "0", "") and pre not in (None, 0, "0", ""):
                chg_amt = round(float(last) - float(pre), 4)
            if chg_pct is None and chg_amt is not None and pre not in (None, 0, "0", ""):
                chg_pct = round(float(chg_amt) / float(pre) * 100, 4)
        except (TypeError, ValueError):
            pass
        # 派生字段
        amplitude: float | None = None
        turnover_amount: float | None = None
        circulating_shares: float | None = None
        turnover_rate: float | None = None
        try:
            high = q.get("high")
            low = q.get("low")
            if high and low and pre:
                amplitude = round((float(high) - float(low)) / float(pre) * 100, 2)
        except (TypeError, ValueError):
            pass
        try:
            # turnover 字段是 **成交额 (元)** (tencent field[37], 注释 "# 元")
            turnover_amount = q.get("turnover")
            if turnover_amount is not None:
                turnover_amount = float(turnover_amount)
        except (TypeError, ValueError):
            turnover_amount = None
        try:
            # 流通股 = 流通市值 / 现价 (现价 > 0 时)
            cap = q.get("circulating_market_cap")
            if cap and last:
                circulating_shares = float(cap) / float(last)
        except (TypeError, ValueError):
            circulating_shares = None
        # 换手率 = 成交量(手) / 流通股(手) = volume(手) / (流通股 / 100)
        try:
            volume = q.get("volume")  # 单位: 手
            if volume is not None and circulating_shares:
                # circulating_shares 是股数, 转成手数 (/100)
                turnover_rate = round(float(volume) / (float(circulating_shares) / 100) * 100, 2)
        except (TypeError, ValueError):
            turnover_rate = None

        constituents.append({
            "code": bare,                        # 去 sz/sh/bj 前缀
            "raw_code": raw,                     # 保留原始带前缀 code, 调试用
            "name": q.get("name") or bare,       # tencent snapshot 自带 name
            "last_price": last,
            "pre_close_price": pre,
            "open": q.get("open"),
            "high": q.get("high"),
            "low": q.get("low"),
            "change_pct": chg_pct,
            "change_amount": chg_amt,
            "amplitude": amplitude,              # 振幅 % = (high - low) / pre_close * 100
            "turnover_amount": turnover_amount,  # 成交额 (元) — 跟 IndustryConstituentRow "成交额" 字段对齐
            "turnover_rate": turnover_rate,      # 换手率 % — 算出来的 (volume / 流通股)
            "volume": q.get("volume"),          # 成交手数
            "circulating_market_cap": q.get("circulating_market_cap"),
            "circulating_shares": circulating_shares,  # 流通股(股)
            "valid": last is not None and pre not in (None, 0, "0", ""),
        })

    from datetime import datetime, timedelta
    # codes 也去前缀, 跟 constituents 里的 code 对齐 (前端 StockDetailDialog 期望 6 位 code)
    bare_codes = [
        (c[2:] if c[:2] in ("sh", "sz", "bj") else c) for c in codes
    ]
    return jsonify({
        "ok": True,
        "name": name,
        "codes": bare_codes,
        "constituents": constituents,
        "sample_size": item.get("sample_size") or len(codes),
        "valid_size": item.get("valid_size"),
        "change_pct": item.get("change_pct"),
        "fetched_at": (datetime.utcnow() + timedelta(hours=8)).isoformat(timespec="seconds"),
    })


# ---------------------------------------------------------------------------
# 涨跌停情绪 (limitEmotion) 路由
#
# 三个端点:
#   GET  /api/stock-chart/market-pulse/limit-emotion
#     - 读盘优先, stale 才重算. 给前端 use.
#   POST /api/stock-chart/market-pulse/limit-emotion/refresh
#     - 强制重算 + 落盘 latest + snapshot.
#   POST /api/stock-chart/market-pulse/limit-emotion/daily-snapshot
#     - 收盘后落盘 daily/<date>.json (供次日连板用).
#   GET  /api/stock-chart/market-pulse/limit-emotion/config
#   PUT  /api/stock-chart/market-pulse/limit-emotion/config
#   GET  /api/stock-chart/market-pulse/limit-emotion/history
#     - 历史序列 (PG → JSON 兜底)
# ---------------------------------------------------------------------------
@stock_chart_bp.route('/api/stock-chart/market-pulse/limit-emotion')
def market_pulse_limit_emotion():
    """返回 limitEmotion 最新结果.

    不存在 / 过旧 → 同步重算一次 (staleMinutes 配置控制).
    """
    try:
        payload = _get_limit_emotion_service()
    except Exception as exc:
        logger.exception("limitEmotion failed: %s", exc)
        return jsonify({
            "ok": False,
            "error": f"limitEmotion failed: {exc}",
            "tradeDate": None,
            "updateTime": None,
            "marketStatus": "unknown",
            "dataStatus": "empty",
        }), 200
    return jsonify({"ok": True, **payload})


@stock_chart_bp.route('/api/stock-chart/market-pulse/limit-emotion/refresh', methods=['POST'])
def market_pulse_limit_emotion_refresh():
    """强制重算 + 落盘."""
    try:
        payload = _build_limit_emotion_service(force=True)
    except Exception as exc:
        logger.exception("limitEmotion refresh failed: %s", exc)
        return jsonify({"ok": False, "error": f"refresh failed: {exc}"}), 200
    return jsonify({"ok": True, **payload})


@stock_chart_bp.route('/api/stock-chart/market-pulse/limit-emotion/daily-snapshot', methods=['POST'])
def market_pulse_limit_emotion_daily_snapshot():
    """收盘落盘 daily/<date>.json (供次日连板).

    非交易日直接返回 ok=False + error 解释, 不写盘.
    """
    try:
        out = _snapshot_today_daily_service(force=True)
    except Exception as exc:
        logger.exception("limitEmotion daily-snapshot failed: %s", exc)
        return jsonify({"ok": False, "error": f"daily snapshot failed: {exc}"}), 200
    if not out:
        return jsonify({
            "ok": False,
            "error": "non-trading day or no quotes available; daily file not written",
        }), 200
    return jsonify({
        "ok": True,
        "tradeDate": out.get("tradeDate"),
        "stockCount": out.get("stockCount"),
        "path": f"reference/market-limit/daily/{out.get('tradeDate')}.json",
    })


@stock_chart_bp.route('/api/stock-chart/market-pulse/limit-emotion/history')
def market_pulse_limit_emotion_history():
    """近 N 日 limit emotion 历史序列 (PG → JSON 兜底).

    URL: GET /api/stock-chart/market-pulse/limit-emotion/history?days=60&end=YYYY-MM-DD
    days 默认 60, 上限 365.
    """
    try:
        raw_days = request.args.get("days") or "60"
        days = max(1, min(int(raw_days), 365))
    except (TypeError, ValueError):
        days = 60
    end_str = (request.args.get("end") or "").strip()

    # 1) Try PG first
    try:
        from backend.config.database import session_scope  # noqa: PLC0415
        from backend.repositories.market.market_limit_pg_repo import (  # noqa: PLC0415
            MarketLimitPgRepository,
        )

        with session_scope() as db:
            repo = MarketLimitPgRepository(db)
            items = repo.get_history(days=days, end_date=end_str if end_str else None)

        if items:
            return jsonify({
                "ok": True,
                "days": days,
                "count": len(items),
                "source": "postgres",
                "items": items,
            })
    except Exception as exc:
        logger.warning("limit emotion history from PG failed, fallback: %s", exc)

    # 2) Fallback: JSON snapshots archive
    # 遍历 reference/market-pulse/snapshots/<date>/ 取每个日期最新的
    from backend.config.settings import MARKET_PULSE_LIMIT_SNAPSHOTS_DIR  # noqa: PLC0415
    from datetime import date as _date, timedelta  # noqa: PLC0415
    # end date
    try:
        end = _date.fromisoformat(end_str) if end_str else _date.today()
    except (TypeError, ValueError):
        end = _date.today()
    start = end - timedelta(days=days * 2)  # 宽松范围 (含非交易日)

    items: list[dict] = []
    current = start
    while current <= end:
        snap_dir = MARKET_PULSE_LIMIT_SNAPSHOTS_DIR / current.isoformat()
        if snap_dir.is_dir():
            snap_files = sorted(snap_dir.glob("*.json"))
            if snap_files:
                try:
                    import json as _json  # noqa: PLC0415
                    payload = _json.loads(snap_files[-1].read_text(encoding="utf-8"))
                    if isinstance(payload, dict):
                        items.append({
                            "trade_date": current.isoformat(),
                            "limit_up_count": (payload.get("limitUp") or {}).get("count"),
                            "limit_down_count": (payload.get("limitDown") or {}).get("count"),
                            "touched_count": (payload.get("breakBoard") or {}).get("touchedCount"),
                            "broken_count": (payload.get("breakBoard") or {}).get("brokenCount"),
                            "break_board_rate": (payload.get("breakBoard") or {}).get("rate"),
                            "max_streak_height": (payload.get("streak") or {}).get("maxHeight"),
                            "sentiment_level": (payload.get("streak") or {}).get("sentiment", {}).get("level"),
                            "stock_count": (payload.get("_meta") or {}).get("stockCount"),
                            "market_status": payload.get("marketStatus"),
                            "data_status": payload.get("dataStatus"),
                            "source": (payload.get("_meta") or {}).get("source"),
                        })
                except Exception:
                    pass
        current += timedelta(days=1)

    items = [it for it in items if it.get("limit_up_count") is not None]
    return jsonify({
        "ok": True,
        "days": days,
        "count": len(items),
        "source": "json_snapshots",
        "items": items[-days:],
    })


@stock_chart_bp.route('/api/stock-chart/market-pulse/limit-emotion/config', methods=['GET'])
def market_pulse_limit_emotion_config_get():
    from backend.services.stock.limit_emotion_service import _load_config  # noqa: SLF001
    return jsonify({"ok": True, "config": _load_config()})


@stock_chart_bp.route('/api/stock-chart/market-pulse/limit-emotion/config', methods=['PUT'])
def market_pulse_limit_emotion_config_put():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"ok": False, "error": "body must be a JSON object"}), 400
    merged = _save_limit_emotion_config(body)
    return jsonify({"ok": True, "config": merged})
