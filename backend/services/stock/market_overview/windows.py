from __future__ import annotations

from dataclasses import dataclass
from math import sqrt


WINDOWS = [5, 10, 15, 20, 30, 60, 100, 120, 250]
FORWARD_WINDOWS = [5, 10, 15, 20, 30, 60, 100, 120, 250]

WINDOW_CONFIG = {
    5: {"slope_lookback": 3, "vol_window": 5, "ma_periods": [5]},
    10: {"slope_lookback": 5, "vol_window": 10, "ma_periods": [5, 10]},
    15: {"slope_lookback": 5, "vol_window": 15, "ma_periods": [10]},
    20: {"slope_lookback": 5, "vol_window": 20, "ma_periods": [20]},
    30: {"slope_lookback": 10, "vol_window": 30, "ma_periods": [20, 30]},
    60: {"slope_lookback": 20, "vol_window": 60, "ma_periods": [20, 60]},
    100: {"slope_lookback": 30, "vol_window": 100, "ma_periods": [60]},
    120: {"slope_lookback": 30, "vol_window": 120, "ma_periods": [60, 120]},
    250: {"slope_lookback": 60, "vol_window": 250, "ma_periods": [120, 250]},
}


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

    last_idx = len(bars) - 1
    close = closes[last_idx]

    precomputed_ma: dict[int, list[float | None]] = {}
    precomputed_vol: dict[int, list[float | None]] = {}

    result: list[dict] = []
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

        cfg = WINDOW_CONFIG.get(window, {})
        slope_lookback = cfg.get("slope_lookback", 5)
        vol_window_cfg = cfg.get("vol_window", window)
        ma_periods = cfg.get("ma_periods", [20, 60])

        window_vol = precomputed_vol.get(vol_window_cfg)
        if window_vol is None:
            window_vol = calc_volatility(returns, vol_window_cfg)
            precomputed_vol[vol_window_cfg] = window_vol
        volatility_val = window_vol[last_idx] if last_idx < len(window_vol) and window_vol[last_idx] is not None else None

        ma_slopes: dict[int, float | None] = {}
        for ma_period in ma_periods:
            ma_vals = precomputed_ma.get(ma_period)
            if ma_vals is None:
                ma_vals = moving_average(closes, ma_period)
                precomputed_ma[ma_period] = ma_vals
            ma_last = ma_vals[last_idx]
            slope = None
            if ma_last and last_idx >= slope_lookback:
                ma_prev = ma_vals[last_idx - slope_lookback]
                if ma_prev and ma_prev != 0:
                    slope = round(ma_last / ma_prev - 1, 4)
            if ma_period == 20:
                ma_slopes[20] = slope
            elif ma_period == 60:
                ma_slopes[60] = slope
            elif ma_period == 5:
                ma_slopes[5] = slope
            elif ma_period == 10:
                ma_slopes[10] = slope
            elif ma_period == 30:
                ma_slopes[30] = slope
            elif ma_period == 120:
                ma_slopes[120] = slope
            elif ma_period == 250:
                ma_slopes[250] = slope

        ma20_vals = precomputed_ma.get(20)
        if ma20_vals is None:
            ma20_vals = moving_average(closes, 20)
            precomputed_ma[20] = ma20_vals
        ma20_last = ma20_vals[last_idx]

        ma60_vals = precomputed_ma.get(60)
        if ma60_vals is None:
            ma60_vals = moving_average(closes, 60)
            precomputed_ma[60] = ma60_vals
        ma60_last = ma60_vals[last_idx]

        entry: dict = {
            'window': window,
            'returnN': round(close / prev_close - 1, 4) if prev_close else None,
            'highN': round(window_high, 2),
            'lowN': round(window_low, 2),
            'rangePosition': round((close - window_low) / range_width, 4) if range_width > 0 else None,
            'drawdownFromHigh': round(close / window_high - 1, 4) if window_high else None,
            'reboundFromLow': round(close / window_low - 1, 4) if window_low else None,
            'volatility': round(volatility_val, 4) if volatility_val is not None else None,
            'upDaysRatio': round(len(up_days) / len(all_days), 4) if all_days else None,
            'volumeRatio': round(volumes[last_idx] / volume_avg, 4) if volume_avg else None,
            'amountRatio': round(amounts[last_idx] / amount_avg, 4) if amount_avg else None,
            'closeAboveMa20': bool(ma20_last is not None and close > ma20_last),
            'closeAboveMa60': bool(ma60_last is not None and close > ma60_last),
            'ma20Slope': ma_slopes.get(20),
            'ma60Slope': ma_slopes.get(60),
        }
        result.append(entry)
    return result


def infer_regime_bucket(range_pos_20: float | None, range_pos_60: float | None, above_ma20: bool, above_ma60: bool, ret20: float | None, ret60: float | None) -> str:
    pos20 = range_pos_20 if range_pos_20 is not None else 0.5
    pos60 = range_pos_60 if range_pos_60 is not None else 0.5
    r20 = ret20 or 0
    r60 = ret60 or 0
    if above_ma20 and above_ma60 and pos60 > 0.68 and r60 > 0.04:
        return 'trend_up'
    if (not above_ma20) and (not above_ma60) and pos60 < 0.32 and r60 < -0.04:
        return 'trend_down'
    if pos20 > 0.78 or pos60 > 0.78:
        return 'near_high'
    if pos20 < 0.22 or pos60 < 0.22:
        return 'near_low'
    if abs(r20) < 0.03 and abs(r60) < 0.05:
        return 'range'
    return 'transition'


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
