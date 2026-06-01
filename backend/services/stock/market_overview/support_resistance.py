from __future__ import annotations

from backend.services.stock.market_overview.windows import PriceLevel


def _append_level(bucket: list[PriceLevel], latest_close: float, price: float, level_type: str, source: str, strength: int, label: str):
    if price <= 0:
        return
    bucket.append(PriceLevel(price, level_type, source, strength, label, price / latest_close - 1))


def _merge_levels(levels: list[PriceLevel], latest_close: float, level_type: str, limit: int = 8) -> list[dict]:
    filtered = [lvl for lvl in levels if lvl.price > 0]
    filtered.sort(key=lambda x: x.price)
    merged: list[PriceLevel] = []
    tolerance = max(latest_close * 0.006, 1)

    for level in filtered:
        if not merged:
            merged.append(level)
            continue
        last = merged[-1]
        if abs(level.price - last.price) <= tolerance:
            total_strength = last.strength + level.strength
            merged_price = ((last.price * last.strength) + (level.price * level.strength)) / total_strength
            merged[-1] = PriceLevel(
                price=merged_price,
                type=level_type,
                source='cluster',
                strength=min(100, total_strength),
                label=f'{last.label} / {level.label}',
                distance_pct=merged_price / latest_close - 1,
            )
        else:
            merged.append(level)

    if level_type == 'support':
        ordered = [lvl for lvl in merged if lvl.price <= latest_close]
    else:
        ordered = [lvl for lvl in merged if lvl.price >= latest_close]
    ordered.sort(key=lambda x: abs(x.distance_pct))
    return [item.to_dict() for item in ordered[:limit]]


def _build_gap_levels(bars: list[dict], latest_close: float) -> tuple[list[PriceLevel], list[PriceLevel]]:
    supports: list[PriceLevel] = []
    resistances: list[PriceLevel] = []
    start = max(1, len(bars) - 120)
    for i in range(start, len(bars)):
        prev_high = float(bars[i - 1]['high'])
        prev_low = float(bars[i - 1]['low'])
        curr_high = float(bars[i]['high'])
        curr_low = float(bars[i]['low'])
        date = str(bars[i].get('timestamp'))

        if curr_low > prev_high:
            gap_pct = curr_low / prev_high - 1
            if gap_pct >= 0.006:
                _append_level(supports, latest_close, prev_high, 'support', 'gap', min(96, 72 + int(gap_pct * 1000)), f'向上缺口下沿 {date}')
                _append_level(supports, latest_close, curr_low, 'support', 'gap', min(98, 75 + int(gap_pct * 1000)), f'向上缺口上沿 {date}')
        if curr_high < prev_low:
            gap_pct = prev_low / curr_high - 1
            if gap_pct >= 0.006:
                _append_level(resistances, latest_close, curr_high, 'resistance', 'gap', min(96, 72 + int(gap_pct * 1000)), f'向下缺口下沿 {date}')
                _append_level(resistances, latest_close, prev_low, 'resistance', 'gap', min(98, 75 + int(gap_pct * 1000)), f'向下缺口上沿 {date}')
    return supports, resistances


def _build_swing_cluster_levels(bars: list[dict], latest_close: float) -> tuple[list[PriceLevel], list[PriceLevel]]:
    supports: list[PriceLevel] = []
    resistances: list[PriceLevel] = []
    if len(bars) < 20:
        return supports, resistances

    start = max(2, len(bars) - 180)
    for i in range(start, len(bars) - 2):
        high = float(bars[i]['high'])
        low = float(bars[i]['low'])
        left_highs = [float(bars[i - 2]['high']), float(bars[i - 1]['high'])]
        right_highs = [float(bars[i + 1]['high']), float(bars[i + 2]['high'])]
        left_lows = [float(bars[i - 2]['low']), float(bars[i - 1]['low'])]
        right_lows = [float(bars[i + 1]['low']), float(bars[i + 2]['low'])]
        date = str(bars[i].get('timestamp'))

        if high >= max(left_highs + right_highs):
            _append_level(resistances, latest_close, high, 'resistance', 'swing', 64, f'波段高点 {date}')
        if low <= min(left_lows + right_lows):
            _append_level(supports, latest_close, low, 'support', 'swing', 64, f'波段低点 {date}')
    return supports, resistances


def _build_volume_node_levels(bars: list[dict], latest_close: float) -> tuple[list[PriceLevel], list[PriceLevel]]:
    sample = bars[-120:]
    if len(sample) < 20:
        return [], []

    low_price = min(float(item['low']) for item in sample)
    high_price = max(float(item['high']) for item in sample)
    if high_price <= low_price:
        return [], []

    bin_count = 12
    step = (high_price - low_price) / bin_count
    bins = [{'weight': 0.0, 'price': low_price + (idx + 0.5) * step} for idx in range(bin_count)]

    for item in sample:
        typical = (float(item['high']) + float(item['low']) + float(item['close'])) / 3
        weight = float(item.get('turnover') or item.get('volume') or 0) or 1
        index = min(bin_count - 1, max(0, int((typical - low_price) / step)))
        bins[index]['weight'] += weight

    sorted_bins = sorted(bins, key=lambda x: x['weight'], reverse=True)[:5]
    supports: list[PriceLevel] = []
    resistances: list[PriceLevel] = []
    max_weight = max(item['weight'] for item in sorted_bins) if sorted_bins else 1

    for item in sorted_bins:
        price = float(item['price'])
        strength = 60 + int((item['weight'] / max_weight) * 30)
        label = '成交密集区'
        if price <= latest_close:
            _append_level(supports, latest_close, price, 'support', 'volumeNode', strength, label)
        else:
            _append_level(resistances, latest_close, price, 'resistance', 'volumeNode', strength, label)
    return supports, resistances


def build_support_resistance(bars: list[dict], window_metrics: list[dict], latest_close: float, ma20: float | None, ma60: float | None, ma120: float | None, ma250: float | None) -> tuple[list[dict], list[dict]]:
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

    gap_supports, gap_resistances = _build_gap_levels(bars, latest_close)
    swing_supports, swing_resistances = _build_swing_cluster_levels(bars, latest_close)
    volume_supports, volume_resistances = _build_volume_node_levels(bars, latest_close)

    supports.extend(gap_supports)
    supports.extend(swing_supports)
    supports.extend(volume_supports)
    resistances.extend(gap_resistances)
    resistances.extend(swing_resistances)
    resistances.extend(volume_resistances)

    supports_sorted = _merge_levels(supports, latest_close, 'support')
    resist_sorted = _merge_levels(resistances, latest_close, 'resistance')
    return supports_sorted, resist_sorted
