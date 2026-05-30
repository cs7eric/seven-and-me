from datetime import datetime
import requests

from backend.config.settings import DOWNLOAD_HEADERS, STOCK_REFERENCE_CACHE_FOLDER
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
        'price': price,
        'volume': volume,
        'amount': amount,
        'matchPrice': match_price,
        'unmatchedBuyVolume': unmatched_buy_volume,
        'unmatchedSellVolume': unmatched_sell_volume,
        'gapRate': gap_rate,
        'auctionVolumeRatio': auction_volume_ratio,
        'unmatchedDelta': unmatched_delta,
        'strengthLabel': strength_label,
    }


def fetch_stock_auction(symbol: str) -> dict:
    code = f'sh{symbol}' if symbol.startswith(('5', '6', '9')) else f'sz{symbol}'
    response = requests.get(
        f'https://qt.gtimg.cn/q={code}',
        headers={'User-Agent': DOWNLOAD_HEADERS['User-Agent'], 'Referer': 'https://gu.qq.com/'},
        timeout=(5, 12),
    )
    response.raise_for_status()
    text = response.text
    if '="' not in text:
        raise ValueError('腾讯竞价接口返回异常')
    payload = text.split('="', 1)[1].rsplit('";', 1)[0]
    parts = payload.split('~')
    if len(parts) < 50:
        raise ValueError('腾讯竞价接口字段不足')

    def to_price(index: int) -> float | None:
        value = parts[index] if len(parts) > index else ''
        try:
            return float(value)
        except ValueError:
            return None

    def to_volume(index: int) -> int | None:
        value = parts[index] if len(parts) > index else ''
        try:
            return int(float(value))
        except ValueError:
            return None

    def to_amount(index: int) -> float | None:
        value = parts[index] if len(parts) > index else ''
        try:
            return float(value)
        except ValueError:
            return None

    quote_time = parts[30] if len(parts) > 30 else ''
    trade_date = f"{quote_time[0:4]}-{quote_time[4:6]}-{quote_time[6:8]}" if len(quote_time) >= 8 else datetime.now().strftime('%Y-%m-%d')
    trade_clock = f"{quote_time[8:10]}:{quote_time[10:12]}:{quote_time[12:14]}" if len(quote_time) >= 14 else None
    prev_close = to_price(4)
    total_volume = to_volume(36)
    total_amount = to_amount(37)
    unmatched_buy_volume = to_volume(10)
    unmatched_sell_volume = to_volume(20)

    opening = build_stock_auction_phase_snapshot(
        time_text='09:25:00',
        price=to_price(5),
        volume=total_volume,
        amount=total_amount,
        match_price=to_price(3),
        unmatched_buy_volume=unmatched_buy_volume,
        unmatched_sell_volume=unmatched_sell_volume,
        prev_close=prev_close,
        total_volume=total_volume,
    )
    closing = build_stock_auction_phase_snapshot(
        time_text=trade_clock or '15:00:00',
        price=to_price(3),
        volume=total_volume,
        amount=total_amount,
        match_price=to_price(3),
        unmatched_buy_volume=unmatched_buy_volume,
        unmatched_sell_volume=unmatched_sell_volume,
        prev_close=prev_close,
        total_volume=total_volume,
    )
    result = {
        'symbol': symbol,
        'trade_date': trade_date,
        'opening': opening,
        'closing': closing,
    }
    cache_file = STOCK_REFERENCE_CACHE_FOLDER / 'auction' / f'{symbol}.json'
    write_json_file(cache_file, result)
    return result
