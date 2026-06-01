from __future__ import annotations

from statistics import median

from backend.adapters.market.eastmoney import fetch_market_breadth
from backend.services.stock.kline_service import resolve_stock_klines
from backend.utils.json_io import read_json_file
from backend.config.settings import STOCK_REFERENCE_CACHE_FOLDER
from backend.services.stock.market_overview_metrics import (
    FORWARD_WINDOWS,
    WINDOWS,
    build_summary,
    build_support_resistance,
    calc_return,
    classify_range_type,
    latest_window_metrics,
    moving_average,
    summarize_forward_stats,
)


INDEX_SYMBOLS = {
    '上证指数': '000001',
    '沪深300': '000300',
    '创业板指': '399006',
    '中证1000': '000852',
    '中证2000': '932000',
    '上证50': '000016',
}

BREADTH_SERIES_CACHE_FILE = STOCK_REFERENCE_CACHE_FOLDER / 'breadth' / 'series.json'


def _sample_loader(symbol: str, period: str) -> list[dict]:
    from backend.services.stock.sample_data_service import sample_stock_klines
    return sample_stock_klines(symbol, period)


def _fetch_index_bars(name: str, symbol: str) -> list[dict]:
    items, _ = resolve_stock_klines('index', symbol, '1d', 'qfq', _sample_loader)
    return items


def _build_style_overview(index_bars_map: dict[str, list[dict]], sh_bars: list[dict]) -> list[dict]:
    def rel_return(name: str, window: int) -> float | None:
        bars = index_bars_map.get(name) or []
        if len(bars) <= window or len(sh_bars) <= window:
            return None
        idx_ret = calc_return(bars, window)
        sh_ret = calc_return(sh_bars, window)
        if idx_ret is None or sh_ret is None:
            return None
        return round(idx_ret - sh_ret, 4)

    rows = [
        {'style': '大盘', 'source': '上证50'},
        {'style': '中盘', 'source': '沪深300'},
        {'style': '小盘', 'source': '中证1000'},
        {'style': '微盘', 'source': '中证2000'},
        {'style': '成长', 'source': '创业板指'},
    ]
    result = []
    for row in rows:
        rel5 = rel_return(row['source'], 5)
        rel20 = rel_return(row['source'], 20)
        rel60 = rel_return(row['source'], 60)
        values = [v for v in [rel5, rel20, rel60] if v is not None]
        avg_score = sum(values) / len(values) if values else 0
        state = '占优' if avg_score > 0.03 else '偏强' if avg_score > 0.01 else '转弱' if avg_score < -0.01 else '均衡'
        result.append({
            'style': row['style'],
            'source': row['source'],
            'relativeReturn5': rel5,
            'relativeReturn20': rel20,
            'relativeReturn60': rel60,
            'state': state,
        })
    return result


def _sentiment_overview() -> dict:
    try:
        today = fetch_market_breadth()
    except Exception:
        today = {}
    series = read_json_file(BREADTH_SERIES_CACHE_FILE, [])
    if not isinstance(series, list):
        series = []
    recent5 = series[-5:]
    recent20 = series[-20:]

    def score(item: dict) -> float:
        up_count = float(item.get('upCount') or 0)
        down_count = float(item.get('downCount') or 0)
        limit_up = float(item.get('limitUpCount') or 0)
        limit_down = float(item.get('limitDownCount') or 0)
        total = float(item.get('totalCount') or (up_count + down_count) or 1)
        breadth = (up_count - down_count) / total
        limit = (limit_up - limit_down) / total
        return max(0.0, min(100.0, 50 + breadth * 45 + limit * 120))

    today_score = round(score(today), 2) if today else 50
    score5 = round(sum(score(x) for x in recent5) / len(recent5), 2) if recent5 else today_score
    score20 = round(sum(score(x) for x in recent20) / len(recent20), 2) if recent20 else today_score
    trend = '改善' if score5 > score20 + 3 else '走弱' if score5 < score20 - 3 else '震荡'
    risk_diffusion = max(0.0, min(100.0, 50 + ((float(today.get('limitDownCount') or 0) - float(today.get('limitUpCount') or 0)) * 0.8))) if today else 50
    state = '偏强' if today_score >= 65 else '中性' if today_score >= 45 else '偏弱'
    return {
        'todayScore': today_score,
        'trendScore': score5,
        'riskDiffusionScore': round(risk_diffusion, 2),
        'state': state,
        'trend': trend,
        'score5': score5,
        'score20': score20,
    }


def _build_similar_scenario_backtest(sh_bars: list[dict], regime: str, window_metrics: list[dict], sentiment: dict, dominant_style: str) -> dict:
    closes = [float(x['close']) for x in sh_bars]
    ma20 = moving_average(closes, 20)
    ma60 = moving_average(closes, 60)

    def state_vector(i: int) -> dict | None:
        if i < 250:
            return None
        close = closes[i]
        high20 = max(float(x['high']) for x in sh_bars[i - 19:i + 1])
        low20 = min(float(x['low']) for x in sh_bars[i - 19:i + 1])
        high60 = max(float(x['high']) for x in sh_bars[i - 59:i + 1])
        low60 = min(float(x['low']) for x in sh_bars[i - 59:i + 1])
        return {
            'date': sh_bars[i].get('timestamp'),
            'shReturn20': close / closes[i - 20] - 1,
            'shReturn60': close / closes[i - 60] - 1,
            'shRangePos20': (close - low20) / (high20 - low20) if high20 > low20 else 0.5,
            'shRangePos60': (close - low60) / (high60 - low60) if high60 > low60 else 0.5,
            'shAboveMa20': bool(ma20[i] and close > ma20[i]),
            'shAboveMa60': bool(ma60[i] and close > ma60[i]),
        }

    current20 = next((item for item in window_metrics if item['window'] == 20), None)
    current60 = next((item for item in window_metrics if item['window'] == 60), None)
    current = {
        'shReturn20': current20.get('returnN') if current20 else 0,
        'shReturn60': current60.get('returnN') if current60 else 0,
        'shRangePos20': current20.get('rangePosition') if current20 else 0.5,
        'shRangePos60': current60.get('rangePosition') if current60 else 0.5,
        'shAboveMa20': current20.get('closeAboveMa20') if current20 else False,
        'shAboveMa60': current20.get('closeAboveMa60') if current20 else False,
    }

    candidates: list[tuple[float, int]] = []
    for i in range(250, len(sh_bars) - max(FORWARD_WINDOWS) - 1):
        vec = state_vector(i)
        if not vec:
            continue
        dist = 0.0
        dist += abs((vec['shRangePos60'] or 0.5) - (current['shRangePos60'] or 0.5)) * 20
        dist += abs((vec['shReturn20'] or 0) - (current['shReturn20'] or 0)) * 100
        dist += abs((vec['shReturn60'] or 0) - (current['shReturn60'] or 0)) * 60
        if vec['shAboveMa20'] != current['shAboveMa20']:
            dist += 8
        if vec['shAboveMa60'] != current['shAboveMa60']:
            dist += 10
        candidates.append((dist, i))
    candidates.sort(key=lambda x: x[0])
    matched = candidates[:40]

    forward_stats = []
    for forward_day in FORWARD_WINDOWS:
        samples = []
        for _, idx in matched:
            entry = closes[idx]
            exit_close = closes[idx + forward_day]
            future_slice = closes[idx + 1:idx + forward_day + 1]
            if not future_slice:
                continue
            min_close = min(future_slice)
            samples.append({
                'return': exit_close / entry - 1,
                'max_drawdown': min_close / entry - 1,
            })
        forward_stats.append(summarize_forward_stats(samples, forward_day))

    conclusion = f'当前情景与历史上 {len(matched)} 个交易日相似，当前识别为 {regime}，主导风格 {dominant_style}，情绪 {sentiment.get("trend") or "震荡"}。'
    return {
        'lookbackWindows': WINDOWS,
        'matchedCount': len(matched),
        'matchedDates': [str(sh_bars[idx].get('timestamp')) for _, idx in matched[:15]],
        'forwardStats': forward_stats,
        'conclusion': conclusion,
    }


def build_market_overview() -> dict:
    index_bars_map = {name: _fetch_index_bars(name, symbol) for name, symbol in INDEX_SYMBOLS.items()}
    sh_bars = index_bars_map['上证指数']
    closes = [float(x['close']) for x in sh_bars]
    latest_close = closes[-1]
    ma20 = moving_average(closes, 20)[-1]
    ma60 = moving_average(closes, 60)[-1]
    ma120 = moving_average(closes, 120)[-1]
    ma250 = moving_average(closes, 250)[-1]

    window_metrics = latest_window_metrics(sh_bars)
    range_type = classify_range_type(window_metrics, latest_close)
    support_levels, resistance_levels = build_support_resistance(window_metrics, latest_close, ma20, ma60, ma120, ma250)
    nearest_support = support_levels[0] if support_levels else None
    nearest_resistance = resistance_levels[0] if resistance_levels else None

    sentiment = _sentiment_overview()
    styles = _build_style_overview(index_bars_map, sh_bars)
    dominant_style = next((item['style'] for item in styles if item['state'] in {'占优', '偏强'}), '均衡')
    risk_state = '中等偏高' if sentiment['riskDiffusionScore'] >= 60 else '中等' if sentiment['riskDiffusionScore'] >= 45 else '偏低'

    summary = build_summary(range_type, window_metrics, sentiment['todayScore'], dominant_style, risk_state, support_levels, resistance_levels)

    indices = []
    for name, bars in index_bars_map.items():
        metrics = latest_window_metrics(bars)
        idx_close = float(bars[-1]['close'])
        idx_range_type = classify_range_type(metrics, idx_close)
        indices.append({
            'name': name,
            'symbol': INDEX_SYMBOLS[name],
            'close': round(idx_close, 2),
            'rangeType': idx_range_type,
            'windowMetrics': metrics,
        })

    industries = []
    for item in styles:
        value20 = item.get('relativeReturn20')
        value60 = item.get('relativeReturn60')
        score = ((value20 or 0) * 100 + (value60 or 0) * 80)
        industries.append({
            'name': item['style'],
            'relativeReturn5': item.get('relativeReturn5'),
            'relativeReturn20': value20,
            'relativeReturn60': value60,
            'state': item['state'],
            'score': round(score, 2),
        })
    industries.sort(key=lambda x: x['score'], reverse=True)

    similar_scenario_backtest = _build_similar_scenario_backtest(sh_bars, range_type, window_metrics, sentiment, dominant_style)

    return {
        'tradeDate': str(sh_bars[-1].get('timestamp')),
        'summary': summary,
        'shanghai': {
            'close': round(latest_close, 2),
            'rangeType': range_type,
            'windowMetrics': window_metrics,
            'supportLevels': support_levels,
            'resistanceLevels': resistance_levels,
            'nearestSupport': nearest_support,
            'nearestResistance': nearest_resistance,
            'ma20': round(ma20, 2) if ma20 else None,
            'ma60': round(ma60, 2) if ma60 else None,
            'ma120': round(ma120, 2) if ma120 else None,
            'ma250': round(ma250, 2) if ma250 else None,
        },
        'indices': indices,
        'sentiment': sentiment,
        'styles': styles,
        'industries': industries,
        'similarScenarioBacktest': similar_scenario_backtest,
    }
