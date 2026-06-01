from __future__ import annotations

from backend.adapters.market.eastmoney import fetch_market_breadth
from backend.config.settings import STOCK_REFERENCE_CACHE_FOLDER
from backend.utils.json_io import read_json_file

BREADTH_SERIES_CACHE_FILE = STOCK_REFERENCE_CACHE_FOLDER / 'breadth' / 'series.json'


def _score_components(item: dict) -> dict:
    up_count = float(item.get('upCount') or 0)
    down_count = float(item.get('downCount') or 0)
    limit_up = float(item.get('limitUpCount') or 0)
    limit_down = float(item.get('limitDownCount') or 0)
    total = float(item.get('totalCount') or (up_count + down_count) or 1)
    break_rate = float(item.get('breakRate') or 0)
    max_lianban = float(item.get('maxLianBan') or 0)
    yesterday_return = float(item.get('yesterdayLimitUpReturn') or 0)
    turnover = float(item.get('totalTurnover') or 0)
    down_over_5 = float(item.get('downOver5Count') or 0)
    new_high_20 = float(item.get('new20HighCount') or 0)
    new_low_20 = float(item.get('new20LowCount') or 0)

    breadth = (up_count - down_count) / total if total else 0
    limit_net = (limit_up - limit_down) / total if total else 0
    break_penalty = 1.0 - min(break_rate / 100.0, 0.6) * 0.8
    lianban_signal = min(max_lianban / 10.0, 0.6) * 0.7
    yesterday_signal = max(-0.4, min(yesterday_return / 2.0, 0.5))
    risk_diff = (down_over_5) / total if total else 0
    trend_strength = (new_high_20 - new_low_20) / total if total else 0

    raw = 50.0
    raw += breadth * 30.0
    raw += limit_net * 40.0
    raw += break_penalty * 10.0
    raw += lianban_signal * 10.0
    raw += yesterday_signal * 8.0
    raw += trend_strength * 10.0
    raw -= risk_diff * 35.0

    return {
        'breadth': round(breadth, 4),
        'limitNet': round(limit_net, 4),
        'breakPenalty': round(break_penalty, 4),
        'lianbanSignal': round(lianban_signal, 4),
        'yesterdaySignal': round(yesterday_signal, 4),
        'riskDiff': round(risk_diff, 4),
        'trendStrength': round(trend_strength, 4),
        'raw': max(0.0, min(100.0, raw)),
        'final': round(max(0.0, min(100.0, raw)), 2),
    }


def _today_score(today: dict) -> float:
    comp = _score_components(today)
    return comp['final']


def build_sentiment_overview() -> dict:
    try:
        today = fetch_market_breadth()
    except Exception:
        today = {}
    series = read_json_file(BREADTH_SERIES_CACHE_FILE, [])
    if not isinstance(series, list):
        series = []

    today_score = _today_score(today) if today else 50.0
    recent5 = series[-5:]
    recent20 = series[-20:]

    scores5 = [_today_score(x) for x in recent5 if x]
    scores20 = [_today_score(x) for x in recent20 if x]

    score5 = round(sum(scores5) / len(scores5), 2) if scores5 else today_score
    score20 = round(sum(scores20) / len(scores20), 2) if scores20 else today_score

    trend = '改善' if score5 > score20 + 3 else '走弱' if score5 < score20 - 3 else '震荡'
    state_label = '偏强' if today_score >= 65 else '中性' if today_score >= 45 else '偏弱'

    risk_diff = max(0.0, min(100.0, 50 + ((float(today.get('limitDownCount') or 0) - float(today.get('limitUpCount') or 0)) * 0.8))) if today else 50

    return {
        'todayScore': today_score,
        'trendScore': score5,
        'riskDiffusionScore': round(risk_diff, 2),
        'state': state_label,
        'trend': trend,
        'score5': score5,
        'score20': score20,
        'limitUpCount': int(today.get('limitUpCount') or 0) if today else 0,
        'limitDownCount': int(today.get('limitDownCount') or 0) if today else 0,
        'breakRate': round(float(today.get('breakRate') or 0), 2) if today else 0,
        'totalTurnover': round(float(today.get('totalTurnover') or 0), 2) if today else 0,
    }


def build_breadth_series_state(series: list[dict], index: int) -> dict | None:
    if index < 19 or index >= len(series):
        return None
    sample = series[index]

    score_today = _today_score(sample)
    recent5_scores = [_today_score(s) for s in series[max(0, index - 4):index + 1]]
    recent20_scores = [_today_score(s) for s in series[index - 19:index + 1]]

    score5 = sum(recent5_scores) / len(recent5_scores) if recent5_scores else score_today
    score20 = sum(recent20_scores) / len(recent20_scores) if recent20_scores else score_today

    trend = '改善' if score5 > score20 + 3 else '走弱' if score5 < score20 - 3 else '震荡'
    state = '偏强' if score_today >= 65 else '中性' if score_today >= 45 else '偏弱'

    up = float(sample.get('upCount') or 0)
    down = float(sample.get('downCount') or 0)
    limit_up = float(sample.get('limitUpCount') or 0)
    limit_down = float(sample.get('limitDownCount') or 0)
    total = float(sample.get('totalCount') or (up + down) or 1)
    risk_diff = max(0.0, min(100.0, 50 + ((limit_down - limit_up) * 0.8)))

    return {
        'date': str(sample.get('date') or sample.get('timestamp') or index),
        'todayScore': round(score_today, 2),
        'score5': round(score5, 2),
        'score20': round(score20, 2),
        'trend': trend,
        'state': state,
        'riskDiffusionScore': round(risk_diff, 2),
    }
