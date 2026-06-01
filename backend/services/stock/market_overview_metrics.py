from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import median

WINDOWS = [5, 10, 15, 20, 30, 60, 100, 120, 250]
FORWARD_WINDOWS = [5, 10, 20, 60, 120, 250]


@dataclass
class PriceLevel:
    price: float
    type: str
    source: str
    strength: int
    label: str
    distance_pct: float

    def to_dict(self) -> dict:
        return {
            'price': round(self.price, 2),
            'type': self.type,
            'source': self.source,
            'strength': self.strength,
            'label': self.label,
            'distancePct': round(self.distance_pct, 4),
        }


def safe_div(a: float, b: float) -> float | None:
    if b is None or b == 0:
        return None
    return a / b


def moving_average(values: list[float], n: int) -> list[float | None]:
    if n <= 0:
        return [None for _ in values]
    result: list[float | None] = []
    acc = 0.0
    for i, value in enumerate(values):
        acc += value
        if i >= n:
            acc -= values[i - n]
        if i >= n - 1:
            result.append(acc / n)
        else:
            result.append(None)
    return result


def calc_atr_pct(bars: list[dict], period: int = 14) -> list[float | None]:
    trs: list[float] = []
    for i, bar in enumerate(bars):
        high = float(bar['high'])
        low = float(bar['low'])
        prev_close = float(bars[i - 1]['close']) if i > 0 else float(bar['close'])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    atr = moving_average(trs, period)
    result: list[float | None] = []
    for idx, bar in enumerate(bars):
        close = float(bar['close'])
        value = safe_div(atr[idx], close) if atr[idx] is not None else None
        result.append(value)
    return result


def calc_daily_returns(closes: list[float]) -> list[float | None]:
    returns: list[float | None] = [None]
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        returns.append((closes[i] / prev - 1) if prev else None)
    return returns


def calc_volatility(returns: list[float | None], window: int) -> list[float | None]:
    result: list[float | None] = []
    for i in range(len(returns)):
        if i < window:
            result.append(None)
            continue
        sample = [v for v in returns[i - window + 1:i + 1] if v is not None]
        if len(sample) < 2:
            result.append(None)
            continue
        mean = sum(sample) / len(sample)
        variance = sum((x - mean) ** 2 for x in sample) / len(sample)
        result.append(sqrt(variance))
    return result


def calc_return(bars: list[dict], window: int) -> float | None:
    if len(bars) <= window:
        return None
    current = float(bars[-1]['close'])
    prev = float(bars[-1 - window]['close'])
    if not prev:
        return None
    return current / prev - 1


def latest_window_metrics(bars: list[dict]) -> list[dict]:
    closes = [float(item['close']) for item in bars]
    highs = [float(item['high']) for item in bars]
    lows = [float(item['low']) for item in bars]
    volumes = [float(item.get('volume') or 0) for item in bars]
    amounts = [float(item.get('turnover') or 0) for item in bars]
    returns = calc_daily_returns(closes)
    atr_pct = calc_atr_pct(bars, 14)
    ma20 = moving_average(closes, 20)
    ma60 = moving_average(closes, 60)
    vol20 = calc_volatility(returns, 20)

    result: list[dict] = []
    last_idx = len(bars) - 1
    close = closes[last_idx]
    ma20_last = ma20[last_idx]
    ma60_last = ma60[last_idx]

    for window in WINDOWS:
        if len(bars) <= window:
            continue
        start = len(bars) - window - 1
        window_high = max(highs[start + 1:])
        window_low = min(lows[start + 1:])
        prev_close = closes[start]
        range_width = window_high - window_low
        up_days = [v for v in returns[start + 1:] if v is not None and v > 0]
        all_days = [v for v in returns[start + 1:] if v is not None]
        volume_avg = sum(volumes[start + 1:]) / window
        amount_avg = sum(amounts[start + 1:]) / window if any(amounts[start + 1:]) else 0

        result.append({
            'window': window,
            'returnN': round(close / prev_close - 1, 4) if prev_close else None,
            'highN': round(window_high, 2),
            'lowN': round(window_low, 2),
            'rangePosition': round((close - window_low) / range_width, 4) if range_width > 0 else None,
            'drawdownFromHigh': round(close / window_high - 1, 4) if window_high else None,
            'reboundFromLow': round(close / window_low - 1, 4) if window_low else None,
            'volatility': round(vol20[last_idx], 4) if vol20[last_idx] is not None else None,
            'atrPct': round(atr_pct[last_idx], 4) if atr_pct[last_idx] is not None else None,
            'upDaysRatio': round(len(up_days) / len(all_days), 4) if all_days else None,
            'volumeRatio': round(volumes[last_idx] / volume_avg, 4) if volume_avg else None,
            'amountRatio': round(amounts[last_idx] / amount_avg, 4) if amount_avg else None,
            'closeAboveMa20': bool(ma20_last is not None and close > ma20_last),
            'closeAboveMa60': bool(ma60_last is not None and close > ma60_last),
            'ma20Slope': round((ma20_last / ma20[last_idx - 5] - 1), 4) if ma20_last and last_idx >= 5 and ma20[last_idx - 5] else None,
            'ma60Slope': round((ma60_last / ma60[last_idx - 5] - 1), 4) if ma60_last and last_idx >= 5 and ma60[last_idx - 5] else None,
        })
    return result


def classify_range_type(window_metrics: list[dict], latest_close: float) -> str:
    wm20 = next((item for item in window_metrics if item['window'] == 20), None)
    wm60 = next((item for item in window_metrics if item['window'] == 60), None)
    wm120 = next((item for item in window_metrics if item['window'] == 120), None)
    if not wm20 or not wm60:
        return '箱体震荡'

    above20 = wm20.get('closeAboveMa20')
    above60 = wm20.get('closeAboveMa60')
    slope20 = wm20.get('ma20Slope') or 0
    slope60 = wm20.get('ma60Slope') or 0
    pos60 = wm60.get('rangePosition') or 0.5
    ret20 = wm20.get('returnN') or 0
    ret60 = wm60.get('returnN') or 0
    pos120 = wm120.get('rangePosition') if wm120 else 0.5

    if above20 and above60 and slope20 > 0 and slope60 > 0 and pos60 > 0.7 and ret60 > 0.05:
        return '主升趋势'
    if above60 and slope60 > 0 and pos60 >= 0.45 and pos60 <= 0.75 and ret20 < 0.03:
        return '上升趋势回踩'
    if pos60 > 0.82 and ret20 > 0 and slope60 <= 0.01:
        return '箱体上沿试探'
    if pos60 < 0.2 and ret20 < 0 and slope20 <= 0:
        return '箱体下沿防守'
    if above20 and not above60 and slope60 < 0 and ret20 > 0:
        return '破位修复'
    if not above20 and not above60 and slope20 < 0 and slope60 < 0 and pos60 < 0.35:
        return '下跌趋势'
    if pos60 < 0.35 and abs(ret20) < 0.03 and abs(slope20) < 0.01:
        return '低位筑底'
    if pos60 > 0.85 and pos120 is not None and pos120 > 0.7 and ret20 > 0.04:
        return '高位钝化'
    return '箱体震荡'


def build_support_resistance(window_metrics: list[dict], latest_close: float, ma20: float | None, ma60: float | None, ma120: float | None, ma250: float | None) -> tuple[list[dict], list[dict]]:
    supports: list[PriceLevel] = []
    resistances: list[PriceLevel] = []

    ma_items = [
        ('MA20', ma20, 'ma', 70),
        ('MA60', ma60, 'ma', 80),
        ('MA120', ma120, 'ma', 85),
        ('MA250', ma250, 'ma', 90),
    ]
    for label, value, source, strength in ma_items:
        if not value:
            continue
        level = PriceLevel(
            price=value,
            type='support' if value <= latest_close else 'resistance',
            source=source,
            strength=strength,
            label=label,
            distance_pct=(value / latest_close - 1),
        )
        (supports if value <= latest_close else resistances).append(level)

    for item in window_metrics:
        window = item['window']
        high_n = item.get('highN')
        low_n = item.get('lowN')
        if high_n:
            resistances.append(PriceLevel(high_n, 'resistance', 'rangeHighLow', 55 + min(window // 5, 35), f'{window}日高点', high_n / latest_close - 1))
        if low_n:
            supports.append(PriceLevel(low_n, 'support', 'rangeHighLow', 55 + min(window // 5, 35), f'{window}日低点', low_n / latest_close - 1))

    supports_sorted = sorted([lvl for lvl in supports if lvl.price <= latest_close], key=lambda x: abs(x.distance_pct))[:8]
    resist_sorted = sorted([lvl for lvl in resistances if lvl.price >= latest_close], key=lambda x: abs(x.distance_pct))[:8]
    return [item.to_dict() for item in supports_sorted], [item.to_dict() for item in resist_sorted]


def market_state_label(window_metric: dict) -> str:
    rp = window_metric.get('rangePosition')
    ret = window_metric.get('returnN') or 0
    if rp is None:
        return '未知'
    if rp > 0.8 and ret > 0:
        return '上沿'
    if rp < 0.2 and ret < 0:
        return '下沿'
    if ret > 0.03:
        return '偏强'
    if ret < -0.03:
        return '偏弱'
    return '震荡'


def build_summary(range_type: str, window_metrics: list[dict], sentiment_score: float, dominant_style: str, risk_state: str, support_levels: list[dict], resistance_levels: list[dict]) -> dict:
    wm20 = next((item for item in window_metrics if item['window'] == 20), None)
    wm60 = next((item for item in window_metrics if item['window'] == 60), None)
    wm250 = next((item for item in window_metrics if item['window'] == 250), None)
    short_state = market_state_label(wm20) if wm20 else '未知'
    mid_state = market_state_label(wm60) if wm60 else '未知'
    long_state = market_state_label(wm250) if wm250 else '未知'
    overall_score = round((sentiment_score * 0.25) + ((wm20.get('rangePosition', 0.5) if wm20 else 0.5) * 100 * 0.25) + ((wm60.get('rangePosition', 0.5) if wm60 else 0.5) * 100 * 0.30) + (55 if '趋势' in range_type else 48) * 0.20)
    nearest_support = support_levels[0]['label'] if support_levels else '暂无'
    nearest_resistance = resistance_levels[0]['label'] if resistance_levels else '暂无'
    conclusion = f'当前市场情景：{range_type}。短期状态 {short_state}，中期状态 {mid_state}，长期背景 {long_state}。主导风格 {dominant_style}，风险状态 {risk_state}。下方关注 {nearest_support}，上方关注 {nearest_resistance}。'
    return {
        'regime': range_type,
        'overallScore': overall_score,
        'shortTermState': short_state,
        'midTermState': mid_state,
        'longTermState': long_state,
        'dominantStyle': dominant_style,
        'riskState': risk_state,
        'conclusion': conclusion,
    }


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
