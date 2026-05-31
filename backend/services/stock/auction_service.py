from datetime import datetime

from backend.adapters.market.eltdx_adapter import fetch_stock_auction_from_eltdx
from backend.config.settings import STOCK_REFERENCE_CACHE_FOLDER
from backend.utils.json_io import write_json_file


def build_stock_auction_phase_snapshot(*, price: float | None, volume: int | None, amount: float | None, match_price: float | None, unmatched_buy_volume: int | None, unmatched_sell_volume: int | None, time_text: str | None, prev_close: float | None, total_volume: int | None) -> dict:
    gap_rate = None
    if price is not None and prev_close not in (None, 0):
        gap_rate = round((price - prev_close) / prev_close * 100, 2)

    auction_volume_ratio = None
    if volume is not None and total_volume not in (None, 0):
        auction_volume_ratio = round(volume / total_volume, 4)

    unmatched_delta = None
    if unmatched_buy_volume is not None and unmatched_sell_volume is not None:
        unmatched_delta = unmatched_buy_volume - unmatched_sell_volume

    strength_label = '中性'
    if gap_rate is not None and unmatched_delta is not None:
        if gap_rate >= 2 and unmatched_delta > 0:
            strength_label = '强势高开'
        elif gap_rate > 0 and unmatched_delta > 0:
            strength_label = '偏强高开'
        elif gap_rate <= -2 and unmatched_delta < 0:
            strength_label = '弱势低开'
        elif gap_rate < 0 and unmatched_delta < 0:
            strength_label = '偏弱低开'

    return {
        'time': time_text,
        'price': round(price, 3) if isinstance(price, (int, float)) else price,
        'volume': volume,
        'amount': round(amount, 2) if isinstance(amount, (int, float)) else amount,
        'matchPrice': round(match_price, 3) if isinstance(match_price, (int, float)) else match_price,
        'unmatchedBuyVolume': unmatched_buy_volume,
        'unmatchedSellVolume': unmatched_sell_volume,
        'gapRate': gap_rate,
        'auctionVolumeRatio': auction_volume_ratio,
        'unmatchedDelta': unmatched_delta,
        'strengthLabel': strength_label,
    }


def _extract_unmatched_side(point: dict) -> tuple[int, int]:
    unmatched_volume = int(point.get('unmatched_volume') or 0)
    unmatched_direction = int(point.get('unmatched_direction_raw') or 0)
    unmatched_buy_volume = unmatched_volume if unmatched_direction > 0 else 0
    unmatched_sell_volume = unmatched_volume if unmatched_direction < 0 else 0
    return unmatched_buy_volume, unmatched_sell_volume


def _score_strength(gap_rate: float | None, unmatched_delta: int | None, volume_ratio: float | None, phase: str) -> str:
    if gap_rate is None:
        return '中性' if phase != 'closing' else '尾盘均衡'

    score = 0.0
    if gap_rate >= 2:
        score += 2
    elif gap_rate > 0:
        score += 1
    elif gap_rate <= -2:
        score -= 2
    elif gap_rate < 0:
        score -= 1

    if unmatched_delta is not None:
        if unmatched_delta >= 5000:
            score += 1.5
        elif unmatched_delta > 0:
            score += 0.5
        elif unmatched_delta <= -5000:
            score -= 1.5
        elif unmatched_delta < 0:
            score -= 0.5

    if volume_ratio is not None:
        direction = 1 if gap_rate > 0 else -1 if gap_rate < 0 else 0
        if volume_ratio >= 0.08:
            score += 2 * direction
        elif volume_ratio >= 0.03:
            score += 1 * direction
        elif volume_ratio < 0.003:
            score -= 0.5 * direction if direction else 0

    if phase == 'closing':
        if score >= 3:
            return '尾盘抢筹'
        if score >= 1:
            return '尾盘偏强'
        if score <= -3:
            return '尾盘抛压'
        if score <= -1:
            return '尾盘偏弱'
        return '尾盘均衡'

    if score >= 3:
        return '强势高开'
    if score >= 1:
        return '偏强高开'
    if score <= -3:
        return '弱势低开'
    if score <= -1:
        return '偏弱低开'
    return '竞价均衡'


def _build_anchor_payload(point: dict | None, *, source: str, exact: bool, target_time: str) -> dict:
    return {
        'point': point,
        'source': source,
        'exact': exact,
        'targetTime': target_time,
        'anchorTime': str((point or {}).get('time_label') or target_time),
    }


def _pick_opening_anchor(points: list[dict], auction_0925: dict) -> dict:
    if auction_0925.get('has_auction_0925'):
        synthetic_point = {
            'time_label': '09:25:00',
            'price': auction_0925.get('price'),
            'matched_volume': auction_0925.get('volume'),
            'unmatched_volume': None,
            'unmatched_direction_raw': 0,
        }
        return _build_anchor_payload(synthetic_point, source='auction0925', exact=True, target_time='09:25:00')

    if not points:
        return _build_anchor_payload(None, source='missing', exact=False, target_time='09:25:00')

    exact_0925 = [point for point in points if str(point.get('time_label') or '') == '09:25:00']
    if exact_0925:
        return _build_anchor_payload(exact_0925[-1], source='openingPoints-exact-0925', exact=True, target_time='09:25:00')

    before_0925 = [point for point in points if str(point.get('time_label') or '') <= '09:25:00']
    if before_0925:
        return _build_anchor_payload(before_0925[-1], source='openingPoints-last-before-0925', exact=False, target_time='09:25:00')

    return _build_anchor_payload(points[-1], source='openingPoints-fallback-last', exact=False, target_time='09:25:00')


def _pick_closing_anchor(points: list[dict]) -> dict:
    if not points:
        return _build_anchor_payload(None, source='missing', exact=False, target_time='15:00:00')

    exact_1500 = [point for point in points if str(point.get('time_label') or '') == '15:00:00']
    if exact_1500:
        return _build_anchor_payload(exact_1500[-1], source='closingPoints-exact-1500', exact=True, target_time='15:00:00')

    before_close = [point for point in points if str(point.get('time_label') or '') <= '15:00:00']
    if before_close:
        return _build_anchor_payload(before_close[-1], source='closingPoints-last-before-1500', exact=False, target_time='15:00:00')

    return _build_anchor_payload(points[-1], source='closingPoints-fallback-last', exact=False, target_time='15:00:00')


def _normalize_price_points(points: list[dict]) -> list[float]:
    normalized = []
    for point in points:
        price = point.get('price')
        if isinstance(price, (int, float)):
            normalized.append(float(price))
    return normalized


def _normalize_matched_volumes(points: list[dict]) -> list[int]:
    return [int(point.get('matched_volume') or 0) for point in points if point.get('matched_volume') is not None]


def _direction_of(point: dict) -> int:
    direction = int(point.get('unmatched_direction_raw') or 0)
    if direction > 0:
        return 1
    if direction < 0:
        return -1
    return 0


def _build_phase_metrics(points: list[dict], phase_snapshot: dict) -> dict:
    prices = _normalize_price_points(points)
    matched_volumes = _normalize_matched_volumes(points)
    recent_points = points[-3:]
    recent_prices = _normalize_price_points(recent_points)
    recent_volumes = _normalize_matched_volumes(recent_points)

    price_range = None
    if prices:
        low = min(prices)
        high = max(prices)
        price_range = {
            'low': round(low, 3),
            'high': round(high, 3),
            'spread': round(high - low, 3),
        }

    recent_price_change = None
    recent_price_trend = '暂无趋势'
    if len(recent_prices) >= 2:
        recent_price_change = round(recent_prices[-1] - recent_prices[0], 3)
        if recent_price_change > 0:
            recent_price_trend = '上行'
        elif recent_price_change < 0:
            recent_price_trend = '下行'
        else:
            recent_price_trend = '走平'

    recent_volume_delta = None
    if len(recent_volumes) >= 2:
        recent_volume_delta = recent_volumes[-1] - recent_volumes[-2]

    directions = [_direction_of(point) for point in points if int(point.get('unmatched_volume') or 0) > 0]
    dominant_direction = '方向未知'
    direction_flip_count = 0
    direction_stability = '暂无方向数据'
    if directions:
        buy_count = sum(1 for item in directions if item > 0)
        sell_count = sum(1 for item in directions if item < 0)
        if buy_count > sell_count:
            dominant_direction = '买方占优'
        elif sell_count > buy_count:
            dominant_direction = '卖方占优'
        else:
            dominant_direction = '买卖拉锯'

        previous = None
        for item in directions:
            if previous is not None and item != previous:
                direction_flip_count += 1
            previous = item

        if direction_flip_count == 0:
            direction_stability = '方向稳定'
        elif direction_flip_count <= 2:
            direction_stability = '方向轻微切换'
        else:
            direction_stability = '方向频繁切换'

    imbalance_pressure = None
    volume = phase_snapshot.get('volume')
    unmatched_delta = phase_snapshot.get('unmatchedDelta')
    if isinstance(volume, int) and volume > 0 and isinstance(unmatched_delta, int):
        imbalance_pressure = round(abs(unmatched_delta) / volume, 4)

    confidence_label = '低'
    if phase_snapshot.get('anchorExact'):
        confidence_label = '高'
    elif directions or price_range or recent_volume_delta is not None:
        confidence_label = '中'

    return {
        'priceRange': price_range,
        'recentPriceTrend': recent_price_trend,
        'recentPriceChange': recent_price_change,
        'recentVolumeDelta': recent_volume_delta,
        'directionStability': direction_stability,
        'directionFlipCount': direction_flip_count,
        'dominantDirection': dominant_direction,
        'imbalancePressure': imbalance_pressure,
        'dataConfidence': confidence_label,
    }


def _build_phase_from_anchor(phase: str, anchor: dict, points: list[dict], prev_close: float | None, total_volume: int | None) -> dict:
    point = anchor.get('point')
    if not point:
        snapshot = build_stock_auction_phase_snapshot(
            time_text=anchor.get('anchorTime'),
            price=None,
            volume=None,
            amount=None,
            match_price=None,
            unmatched_buy_volume=None,
            unmatched_sell_volume=None,
            prev_close=prev_close,
            total_volume=total_volume,
        )
        snapshot['anchorExact'] = bool(anchor.get('exact'))
        snapshot['anchorSource'] = anchor.get('source')
        snapshot['anchorTargetTime'] = anchor.get('targetTime')
        snapshot.update(_build_phase_metrics(points, snapshot))
        return snapshot

    unmatched_buy_volume, unmatched_sell_volume = _extract_unmatched_side(point)
    matched_volume = int(point.get('matched_volume') or 0)
    price = point.get('price')
    amount = point.get('matched_amount_estimated')
    if amount is None and price is not None and matched_volume:
        amount = float(price) * matched_volume * 100

    snapshot = build_stock_auction_phase_snapshot(
        time_text=str(point.get('time_label') or ''),
        price=float(price) if price is not None else None,
        volume=matched_volume,
        amount=float(amount) if amount is not None else None,
        match_price=float(price) if price is not None else None,
        unmatched_buy_volume=unmatched_buy_volume,
        unmatched_sell_volume=unmatched_sell_volume,
        prev_close=prev_close,
        total_volume=total_volume,
    )
    snapshot['strengthLabel'] = _score_strength(snapshot.get('gapRate'), snapshot.get('unmatchedDelta'), snapshot.get('auctionVolumeRatio'), phase)
    snapshot['anchorExact'] = bool(anchor.get('exact'))
    snapshot['anchorSource'] = anchor.get('source')
    snapshot['anchorTargetTime'] = anchor.get('targetTime')
    snapshot.update(_build_phase_metrics(points, snapshot))
    return snapshot


def fetch_stock_auction(symbol: str) -> dict:
    eltdx_payload = fetch_stock_auction_from_eltdx(symbol)
    quote = eltdx_payload.get('quote') or {}
    opening_points = eltdx_payload.get('openingPoints') or []
    closing_points = eltdx_payload.get('closingPoints') or []
    auction_0925 = eltdx_payload.get('auction0925') or {}

    prev_close = quote.get('pre_close_price')
    total_volume = quote.get('total_hand')
    opening_anchor = _pick_opening_anchor(opening_points, auction_0925)
    closing_anchor = _pick_closing_anchor(closing_points)
    opening = _build_phase_from_anchor('opening', opening_anchor, opening_points, prev_close, total_volume)
    closing = _build_phase_from_anchor('closing', closing_anchor, closing_points, prev_close, total_volume)

    result = {
        'symbol': symbol,
        'trade_date': eltdx_payload.get('trade_date') or datetime.now().strftime('%Y-%m-%d'),
        'opening': opening,
        'closing': closing,
        'details': {
            'quote': quote,
            'auction0925': auction_0925,
            'openingPoints': opening_points,
            'closingPoints': closing_points,
            'allPoints': eltdx_payload.get('allPoints') or [],
        },
    }
    cache_file = STOCK_REFERENCE_CACHE_FOLDER / 'auction' / f'{symbol}.json'
    write_json_file(cache_file, result)
    return result
