from __future__ import annotations

from statistics import median

from backend.config.settings import STOCK_REFERENCE_CACHE_FOLDER
from backend.services.stock.market_overview.style_rotation import (
    dominant_style_from_rows,
    style_similarity,
)
from backend.services.stock.market_overview.sentiment import (
    build_breadth_series_state,
)
from backend.services.stock.market_overview.windows import (
    FORWARD_WINDOWS,
    WINDOWS,
    infer_regime_bucket,
    moving_average,
)

BREADTH_SERIES_CACHE_FILE = STOCK_REFERENCE_CACHE_FOLDER / 'breadth' / 'series.json'


def summarize_forward_stats(samples: list[dict], forward_day: int) -> dict:
    returns = [item['return'] for item in samples if item.get('return') is not None]
    drawdowns = [item['max_drawdown'] for item in samples if item.get('max_drawdown') is not None]
    if not returns:
        return {
            'forwardDays': forward_day,
            'winRate': 0,
            'avgReturn': 0,
            'medianReturn': 0,
            'maxReturn': 0,
            'worstReturn': 0,
            'medianMaxDrawdown': 0,
            'positiveRatio': 0,
        }
    positive = [value for value in returns if value > 0]
    return {
        'forwardDays': forward_day,
        'winRate': round(len(positive) / len(returns), 4),
        'avgReturn': round(sum(returns) / len(returns), 4),
        'medianReturn': round(median(returns), 4),
        'maxReturn': round(max(returns), 4),
        'worstReturn': round(min(returns), 4),
        'medianMaxDrawdown': round(median(drawdowns), 4) if drawdowns else 0,
        'positiveRatio': round(len(positive) / len(returns), 4),
    }


def _style_snapshot(index_bars_map: dict[str, list[dict]], sh_bars: list[dict], index_pos: int) -> dict | None:
    if index_pos < 60:
        return None
    from backend.services.stock.market_overview.style_rotation import build_style_overview

    short_index_map = {}
    for name, bars in index_bars_map.items():
        if len(bars) > index_pos:
            short_index_map[name] = bars[:index_pos + 1]
    if not short_index_map:
        return None
    sh_slice = sh_bars[:index_pos + 1]
    rows = build_style_overview(short_index_map, sh_slice)
    return {
        'rows': rows,
        'dominantStyle': dominant_style_from_rows(rows),
    }


def build_similar_scenario_backtest(
    sh_bars: list[dict],
    regime: str,
    window_metrics: list[dict],
    sentiment: dict,
    dominant_style: str,
    index_bars_map: dict[str, list[dict]],
) -> dict:
    from backend.utils.json_io import read_json_file

    closes = [float(x['close']) for x in sh_bars]
    breadth_series = read_json_file(BREADTH_SERIES_CACHE_FILE, [])
    if not isinstance(breadth_series, list):
        breadth_series = []

    ma20 = moving_average(closes, 20)
    ma60 = moving_average(closes, 60)
    wm20 = next((item for item in window_metrics if item['window'] == 20), None)
    wm60 = next((item for item in window_metrics if item['window'] == 60), None)
    current_bucket = infer_regime_bucket(
        wm20.get('rangePosition') if wm20 else None,
        wm60.get('rangePosition') if wm60 else None,
        bool(wm20.get('closeAboveMa20')) if wm20 else False,
        bool(wm20.get('closeAboveMa60')) if wm20 else False,
        wm20.get('returnN') if wm20 else None,
        wm60.get('returnN') if wm60 else None,
    )
    min_history = 120

    def state_vector(i: int) -> dict | None:
        if i < min_history or i >= len(sh_bars):
            return None
        close = closes[i]
        high5 = max(float(x['high']) for x in sh_bars[i - 4:i + 1])
        low5 = min(float(x['low']) for x in sh_bars[i - 4:i + 1])
        high20 = max(float(x['high']) for x in sh_bars[i - 19:i + 1])
        low20 = min(float(x['low']) for x in sh_bars[i - 19:i + 1])
        high60 = max(float(x['high']) for x in sh_bars[i - 59:i + 1])
        low60 = min(float(x['low']) for x in sh_bars[i - 59:i + 1])
        high120 = max(float(x['high']) for x in sh_bars[i - 119:i + 1])
        low120 = min(float(x['low']) for x in sh_bars[i - 119:i + 1])
        breadth_state = build_breadth_series_state(breadth_series, i) if len(breadth_series) > i else None
        style_state = _style_snapshot(index_bars_map, sh_bars, i)
        if not style_state:
            return None
        ret5 = close / closes[i - 5] - 1 if i >= 5 else None
        ret20 = close / closes[i - 20] - 1
        ret60 = close / closes[i - 60] - 1
        ret120 = close / closes[i - 120] - 1
        range_pos5 = (close - low5) / (high5 - low5) if high5 > low5 else 0.5
        range_pos20 = (close - low20) / (high20 - low20) if high20 > low20 else 0.5
        range_pos60 = (close - low60) / (high60 - low60) if high60 > low60 else 0.5
        range_pos120 = (close - low120) / (high120 - low120) if high120 > low120 else 0.5
        above_ma20 = bool(ma20[i] and close > ma20[i])
        above_ma60 = bool(ma60[i] and close > ma60[i])
        regime_bucket = infer_regime_bucket(range_pos20, range_pos60, above_ma20, above_ma60, ret20, ret60)
        ma20_val = ma20[i]
        ma60_val = ma60[i]
        ma20_slope = (ma20_val / ma20[i - 5] - 1) if ma20_val and i >= 5 and ma20[i - 5] else 0
        ma60_slope = (ma60_val / ma60[i - 20] - 1) if ma60_val and i >= 20 and ma60[i - 20] else 0
        return {
            'date': str(sh_bars[i].get('timestamp')),
            'shReturn5': ret5,
            'shReturn20': ret20,
            'shReturn60': ret60,
            'shReturn120': ret120,
            'shRangePos5': range_pos5,
            'shRangePos20': range_pos20,
            'shRangePos60': range_pos60,
            'shRangePos120': range_pos120,
            'shAboveMa20': above_ma20,
            'shAboveMa60': above_ma60,
            'ma20Slope': ma20_slope,
            'ma60Slope': ma60_slope,
            'breadthTodayScore': breadth_state.get('todayScore') if breadth_state else 50,
            'breadthTrendScore': breadth_state.get('score5') if breadth_state else 50,
            'riskDiffusionScore': breadth_state.get('riskDiffusionScore') if breadth_state else 50,
            'sentimentTrend': breadth_state.get('trend') if breadth_state else '震荡',
            'dominantStyle': style_state['dominantStyle'],
            'regimeBucket': regime_bucket,
        }

    current = {
        'shReturn5': next((item.get('returnN') for item in window_metrics if item['window'] == 5), 0) or 0,
        'shReturn20': wm20.get('returnN') if wm20 else 0 or 0,
        'shReturn60': wm60.get('returnN') if wm60 else 0 or 0,
        'shReturn120': next((item.get('returnN') for item in window_metrics if item['window'] == 120), 0) or 0,
        'shRangePos5': next((item.get('rangePosition') for item in window_metrics if item['window'] == 5), 0.5) or 0.5,
        'shRangePos20': wm20.get('rangePosition') if wm20 else 0.5 or 0.5,
        'shRangePos60': wm60.get('rangePosition') if wm60 else 0.5 or 0.5,
        'shRangePos120': next((item.get('rangePosition') for item in window_metrics if item['window'] == 120), 0.5) or 0.5,
        'shAboveMa20': wm20.get('closeAboveMa20') if wm20 else False,
        'shAboveMa60': wm20.get('closeAboveMa60') if wm20 else False,
        'ma20Slope': wm20.get('ma20Slope') or 0,
        'ma60Slope': wm20.get('ma60Slope') or 0,
        'breadthTodayScore': sentiment.get('todayScore') or 50,
        'breadthTrendScore': sentiment.get('score5') or 50,
        'riskDiffusionScore': sentiment.get('riskDiffusionScore') or 50,
        'sentimentTrend': sentiment.get('trend') or '震荡',
        'dominantStyle': dominant_style,
        'regimeBucket': current_bucket,
    }

    candidates: list[tuple[float, int, dict]] = []
    upper_bound = len(sh_bars) - max(FORWARD_WINDOWS)
    for i in range(min_history, upper_bound):
        vec = state_vector(i)
        if not vec:
            continue
        dist = 0.0
        dist += abs((vec['shRangePos5'] or 0.5) - (current['shRangePos5'])) * 6
        dist += abs((vec['shRangePos20'] or 0.5) - (current['shRangePos20'])) * 10
        dist += abs((vec['shRangePos60'] or 0.5) - (current['shRangePos60'])) * 16
        dist += abs((vec['shRangePos120'] or 0.5) - (current['shRangePos120'])) * 8
        dist += abs((vec['shReturn5'] or 0) - (current['shReturn5'])) * 120
        dist += abs((vec['shReturn20'] or 0) - (current['shReturn20'])) * 80
        dist += abs((vec['shReturn60'] or 0) - (current['shReturn60'])) * 55
        dist += abs((vec['shReturn120'] or 0) - (current['shReturn120'])) * 35
        dist += abs(vec['ma20Slope'] - current['ma20Slope']) * 200
        dist += abs(vec['ma60Slope'] - current['ma60Slope']) * 150
        dist += abs((vec['breadthTodayScore'] or 50) - (current['breadthTodayScore'])) * 0.22
        dist += abs((vec['breadthTrendScore'] or 50) - (current['breadthTrendScore'])) * 0.15
        dist += abs((vec['riskDiffusionScore'] or 50) - (current['riskDiffusionScore'])) * 0.15
        if vec['shAboveMa20'] != current['shAboveMa20']:
            dist += 5
        if vec['shAboveMa60'] != current['shAboveMa60']:
            dist += 7
        if vec['sentimentTrend'] != current['sentimentTrend']:
            dist += 3.5
        if vec['regimeBucket'] != current['regimeBucket']:
            dist += 7
        dist += style_similarity(str(vec['dominantStyle']), str(current['dominantStyle']))
        candidates.append((dist, i, vec))

    candidates.sort(key=lambda x: x[0])
    pool = [item for item in candidates if item[0] <= 42]
    if len(pool) < 12:
        pool = candidates[:20]
    matched = pool[:40]

    forward_stats = []
    for forward_day in FORWARD_WINDOWS:
        samples = []
        for _, idx, _ in matched:
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

    matched_details = [
        {
            'date': vec['date'],
            'distance': round(distance, 2),
            'regimeBucket': vec['regimeBucket'],
            'dominantStyle': vec['dominantStyle'],
            'sentimentTrend': vec['sentimentTrend'],
            'rangePos60': round(vec['shRangePos60'], 4),
            'return20': round(vec['shReturn20'], 4),
            'return60': round(vec['shReturn60'], 4),
        }
        for distance, _, vec in matched[:12]
    ]
    median_distance = round(median([item[0] for item in matched]), 2) if matched else None
    conclusion = f'当前情景与历史上 {len(matched)} 个交易日相近，当前识别为 {regime}，主导风格 {dominant_style}，情绪 {sentiment.get("trend") or "震荡"}。'
    return {
        'lookbackWindows': WINDOWS,
        'matchedCount': len(matched),
        'matchedDates': [str(sh_bars[idx].get('timestamp')) for _, idx, _ in matched[:15]],
        'medianDistance': median_distance,
        'matchThreshold': 42,
        'matchedDetails': matched_details,
        'forwardStats': forward_stats,
        'conclusion': conclusion,
    }
