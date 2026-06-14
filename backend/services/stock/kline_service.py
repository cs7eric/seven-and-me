from backend.adapters.market.common import BEIJING_TZ
from datetime import datetime, timezone, timedelta
from typing import Callable

from backend.adapters.market.eastmoney import fetch_stock_klines_from_eastmoney
from backend.adapters.market.eltdx_adapter import fetch_stock_history_timeshare_from_eltdx, fetch_stock_klines_from_eltdx
from backend.adapters.market.mootdx_adapter import fetch_stock_klines_from_mootdx, is_minute_stock_period
from backend.adapters.market.sina import fetch_stock_klines_from_sina
from backend.adapters.market.tencent import fetch_stock_klines_from_tencent
from backend.repositories.stock.workspace_repo import read_cached_stock_intraday, read_cached_stock_klines, stock_intraday_cache_file
from backend.services.stock.config_service import get_stock_chart_config
from backend.utils.json_io import write_json_file


def get_stock_kline_provider_plan(period: str) -> list[str]:
    kline_config = get_stock_chart_config().get('kline', {})
    if period == '1w':
        primary = str(kline_config.get('weekly_provider', 'tencent'))
        fallbacks = kline_config.get('fallbacks', {}).get('weekly', [])
    elif is_minute_stock_period(period):
        primary = str(kline_config.get('minute_provider', 'mootdx'))
        fallbacks = kline_config.get('fallbacks', {}).get('minute', [])
    else:
        primary = str(kline_config.get('daily_provider', 'tencent'))
        fallbacks = kline_config.get('fallbacks', {}).get('daily', [])
    plan: list[str] = []
    for item in [primary, *(fallbacks if isinstance(fallbacks, list) else [])]:
        key = str(item).strip()
        if key and key not in plan:
            plan.append(key)
    return plan


def resolve_stock_klines(target_type: str, symbol: str, period: str, adjust: str, sample_loader) -> tuple[list[dict], str]:
    providers = {
        'eltdx': fetch_stock_klines_from_eltdx,
        'mootdx': fetch_stock_klines_from_mootdx,
        'sina': fetch_stock_klines_from_sina,
        'tencent': fetch_stock_klines_from_tencent,
        'eastmoney': fetch_stock_klines_from_eastmoney,
    }
    for provider_name in get_stock_kline_provider_plan(period):
        provider = providers.get(provider_name)
        if not provider:
            continue
        try:
            items = provider(target_type, symbol, period, adjust)
            if items:
                return items, provider_name
        except Exception:
            continue

    cached_items = read_cached_stock_klines(target_type, symbol, period, adjust)
    if cached_items:
        return cached_items, 'cache'

    if is_minute_stock_period(period):
        raise ValueError('分钟K线真实数据暂不可用')

    return sample_loader(symbol, period), 'sample'


def _trade_date_from_timestamp(timestamp: int | float | None) -> str | None:
    if not isinstance(timestamp, (int, float)):
        return None
    try:
        # K 线 / 分时一律按北京时间计算 trade_date
        return datetime.fromtimestamp(float(timestamp) / 1000, tz=BEIJING_TZ).strftime('%Y-%m-%d')
    except Exception:
        return None


def _trade_date_from_item(item: dict) -> str | None:
    direct = item.get('trade_date') or item.get('date')
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    return _trade_date_from_timestamp(item.get('timestamp'))


def _ensure_trade_date(item: dict) -> dict:
    row = dict(item)
    if not row.get('trade_date'):
        trade_date = _trade_date_from_item(row)
        if trade_date:
            row['trade_date'] = trade_date
    return row


def _infer_average_price(turnover: float, volume: float, close_price: float) -> float | None:
    if turnover <= 0 or volume <= 0:
        return close_price if close_price > 0 else None

    direct = turnover / volume
    scaled = turnover / (volume * 100)
    candidates = [value for value in (direct, scaled) if value > 0]
    if not candidates:
        return close_price if close_price > 0 else None
    if close_price <= 0:
        return round(min(candidates), 4)

    best = min(candidates, key=lambda value: abs(value - close_price))
    return round(best, 4)


def filter_intraday_bars_by_trade_date(items: list[dict], trade_date: str | None = None) -> tuple[str | None, list[dict]]:
    dated_items: list[tuple[str, dict]] = []
    for item in items:
        date_key = _trade_date_from_item(item)
        if not date_key:
            continue
        dated_items.append((date_key, item))

    if not dated_items:
        return None, []

    target_date = trade_date.strip() if isinstance(trade_date, str) and trade_date.strip() else None
    if target_date:
        matched = [item for date_key, item in dated_items if date_key == target_date]
        return target_date, matched

    latest_date = max(date_key for date_key, _ in dated_items)
    return latest_date, [item for date_key, item in dated_items if date_key == latest_date]


def _intraday_providers() -> list[tuple[str, Callable]]:
    return [
        ('eltdx', fetch_stock_klines_from_eltdx),
        ('eastmoney', fetch_stock_klines_from_eastmoney),
        ('tencent', fetch_stock_klines_from_tencent),
        ('sina', fetch_stock_klines_from_sina),
        ('mootdx', fetch_stock_klines_from_mootdx),
    ]


def _supported_intraday_periods(period: str) -> bool:
    return period in {'1m', '5m', '15m', '30m', '60m', '120m'}


def _ensure_periods_argument(periods: list[str] | None) -> list[str]:
    default_periods = ['1m', '5m', '15m', '30m']
    if not periods:
        return default_periods
    cleaned: list[str] = []
    for item in periods:
        value = str(item or '').strip()
        if not value or not _supported_intraday_periods(value):
            continue
        if value not in cleaned:
            cleaned.append(value)
    return cleaned or default_periods


def _load_period_bars_for_trade_date(
    target_type: str,
    symbol: str,
    period: str,
    adjust: str,
    trade_date: str | None = None,
) -> tuple[list[dict], str | None]:
    for provider_name, provider in _intraday_providers():
        try:
            if provider_name == 'eltdx':
                candidate_rows = provider(target_type, symbol, period, adjust, trade_date=trade_date)
            else:
                candidate_rows = provider(target_type, symbol, period, adjust)
            candidate_items = [_ensure_trade_date(item) for item in candidate_rows]
        except Exception:
            continue
        if trade_date:
            resolved_trade_date, matched_items = filter_intraday_bars_by_trade_date(candidate_items, trade_date)
            if matched_items and resolved_trade_date == trade_date:
                return matched_items, provider_name
        else:
            if candidate_items:
                return candidate_items, provider_name

    cached_items = [_ensure_trade_date(item) for item in read_cached_stock_klines(target_type, symbol, period, adjust)]
    if trade_date:
        resolved_trade_date, matched_items = filter_intraday_bars_by_trade_date(cached_items, trade_date)
        if matched_items and resolved_trade_date == trade_date:
            return matched_items, 'cache'
    else:
        if cached_items:
            return cached_items, 'cache'

    return [], None



def _load_intraday_bars(
    target_type: str,
    symbol: str,
    adjust: str,
    trade_date: str | None,
    periods: list[str],
    recent_days: int = 5,
) -> dict[str, tuple[list[dict], str | None]]:
    """对一组 period 各自拉数据。

    - trade_date 给定 → 只返回那一天
    - trade_date 缺失 → 返回"最近 N 个交易日"
    """
    minute_adjust = 'none'
    results: dict[str, tuple[list[dict], str | None]] = {}
    if trade_date:
        for period in periods:
            items, source = _load_period_bars_for_trade_date(
                target_type, symbol, period, minute_adjust, trade_date,
            )
            results[period] = (items, source)
        return results

    for period in periods:
        live_items, live_source = _load_period_bars_for_trade_date(
            target_type, symbol, period, minute_adjust, None,
        )
        cached_items = [_ensure_trade_date(item) for item in read_cached_stock_klines(target_type, symbol, period, minute_adjust)]
        if not live_items and not cached_items:
            results[period] = ([], None)
            continue
        merged: list[dict] = []
        seen: set[tuple[int, str]] = set()
        for source_items in (live_items, cached_items):
            for item in source_items:
                key = (int(item.get('timestamp') or 0), str(item.get('trade_date') or ''))
                if key in seen:
                    continue
                seen.add(key)
                merged.append(item)
        merged.sort(key=lambda row: float(row.get('timestamp') or 0))
        dates = sorted({_trade_date_from_item(item) for item in merged if _trade_date_from_item(item)})
        keep_dates = set(dates[-recent_days:])
        filtered = [item for item in merged if _trade_date_from_item(item) in keep_dates]
        source = live_source or ('cache' if cached_items else None)
        results[period] = (filtered, source)
    return results

def build_intraday_timeshare(items: list[dict]) -> list[dict]:
    points: list[dict] = []
    cumulative_turnover = 0.0
    cumulative_volume = 0.0

    for item in sorted(items, key=lambda row: float(row.get('timestamp') or 0)):
        timestamp = int(item.get('timestamp') or 0)
        if timestamp <= 0:
            continue
        close_price = float(item.get('close') or 0)
        volume = float(item.get('volume') or 0)
        turnover = float(item.get('turnover') or 0)
        turnover_rate = item.get('turnover_rate')
        cumulative_turnover += max(turnover, 0.0)
        cumulative_volume += max(volume, 0.0)

        avg_price = _infer_average_price(cumulative_turnover, cumulative_volume, close_price)
        trade_date = item.get('trade_date') or _trade_date_from_timestamp(timestamp)
        points.append({
            'timestamp': timestamp,
            'trade_date': trade_date,
            'time_label': datetime.fromtimestamp(timestamp / 1000).strftime('%H:%M'),
            'price': round(close_price, 4),
            'avg_price': avg_price,
            'volume': volume,
            'turnover': turnover,
            'turnover_rate': float(turnover_rate) if isinstance(turnover_rate, (int, float)) else None,
        })

    return points


def aggregate_intraday_bars(items: list[dict], interval_minutes: int) -> list[dict]:
    if interval_minutes <= 1:
        return [dict(item) for item in sorted(items, key=lambda row: float(row.get('timestamp') or 0))]

    buckets: list[dict] = []
    current_bucket: dict | None = None
    current_bucket_key: str | None = None

    for item in sorted(items, key=lambda row: float(row.get('timestamp') or 0)):
        timestamp = item.get('timestamp')
        if not isinstance(timestamp, (int, float)):
            continue
        dt = datetime.fromtimestamp(float(timestamp) / 1000)
        bucket_minute = (dt.minute // interval_minutes) * interval_minutes
        bucket_dt = dt.replace(minute=bucket_minute, second=0, microsecond=0)
        bucket_key = bucket_dt.strftime('%Y-%m-%d %H:%M')

        open_price = float(item.get('open') or 0)
        high_price = float(item.get('high') or 0)
        low_price = float(item.get('low') or 0)
        close_price = float(item.get('close') or 0)
        volume = float(item.get('volume') or 0)
        turnover = float(item.get('turnover') or 0)
        turnover_rate = item.get('turnover_rate')

        if bucket_key != current_bucket_key:
            current_bucket = {
                'timestamp': int(bucket_dt.timestamp() * 1000),
                'trade_date': bucket_dt.strftime('%Y-%m-%d'),
                'open': open_price,
                'high': high_price,
                'low': low_price,
                'close': close_price,
                'volume': volume,
                'turnover': turnover,
                'turnover_rate': float(turnover_rate) if isinstance(turnover_rate, (int, float)) else None,
                'volume_ratio': item.get('volume_ratio'),
            }
            buckets.append(current_bucket)
            current_bucket_key = bucket_key
            continue

        if current_bucket is None:
            continue

        current_bucket['high'] = max(float(current_bucket.get('high') or 0), high_price)
        current_bucket['low'] = min(float(current_bucket.get('low') or 0), low_price)
        current_bucket['close'] = close_price
        current_bucket['volume'] = float(current_bucket.get('volume') or 0) + volume
        current_bucket['turnover'] = float(current_bucket.get('turnover') or 0) + turnover

        existing_rate = current_bucket.get('turnover_rate')
        next_rate = float(turnover_rate) if isinstance(turnover_rate, (int, float)) else None
        if next_rate is not None:
            current_bucket['turnover_rate'] = round(float(existing_rate or 0) + next_rate, 4)

    return buckets


def build_intraday_snapshot(
    target_type: str,
    symbol: str,
    adjust: str,
    sample_loader,
    trade_date: str | None = None,
    periods: list[str] | None = None,
) -> tuple[dict, str]:
    minute_adjust = 'none'
    requested_trade_date = trade_date.strip() if isinstance(trade_date, str) and trade_date.strip() else None
    requested_periods = _ensure_periods_argument(periods)
    if requested_trade_date:
        cached_snapshot = read_cached_stock_intraday(target_type, symbol, requested_trade_date)
        cached_requested_trade_date = (
            cached_snapshot.get('requested_trade_date')
            if isinstance(cached_snapshot, dict)
            else None
        )
        if (
            isinstance(cached_snapshot, dict)
            and cached_snapshot.get('trade_date') == requested_trade_date
            and cached_requested_trade_date == requested_trade_date
            and set(requested_periods).issubset(set(cached_snapshot.get('requested_periods') or requested_periods))
        ):
            cached_source = str(cached_snapshot.get('source') or 'cache')
            snapshot = {key: value for key, value in cached_snapshot.items() if key not in {'source', 'requested_periods'}}
            snapshot['requested_periods'] = requested_periods
            return snapshot, cached_source

    minute_periods = [period for period in requested_periods if _supported_intraday_periods(period)]
    bars_by_period = _load_intraday_bars(target_type, symbol, minute_adjust, requested_trade_date, minute_periods)

    if not any(items for items, _ in bars_by_period.values()):
        if requested_trade_date:
            raise ValueError(f'未获取到 {requested_trade_date} 对应交易日的分钟级数据')
        raise ValueError('未获取到对应交易日的分钟级数据')

    primary_period = '1m' if '1m' in minute_periods else minute_periods[0]
    primary_items, primary_source = bars_by_period.get(primary_period, ([], None))
    resolved_trade_date = _trade_date_from_item(primary_items[0]) if primary_items else requested_trade_date

    minute_bars_payload: dict[str, list[dict]] = {}
    period_sources: dict[str, str | None] = {}
    for period in minute_periods:
        items, source = bars_by_period.get(period, ([], None))
        minute_bars_payload[period] = items
        period_sources[period] = source

    source = primary_source or 'unknown'
    timeshare: list[dict] = []
    timeshare_source = None

    # 历史分时：1) 优先按 trade_date 走 eltdx.get_history_minute；2) 失败就用 1m 历史 bars 构造
    timeshare_trade_dates: list[str] = []
    if requested_trade_date:
        timeshare_trade_dates = [requested_trade_date]
    else:
        for period in minute_periods:
            items, _ = bars_by_period.get(period, ([], None))
            for item in items:
                date_key = _trade_date_from_item(item)
                if date_key and date_key not in timeshare_trade_dates:
                    timeshare_trade_dates.append(date_key)
        timeshare_trade_dates.sort()

    for date_key in timeshare_trade_dates:
        try:
            daily_points = fetch_stock_history_timeshare_from_eltdx(symbol, date_key, target_type=target_type)
            if daily_points:
                if not timeshare_source:
                    timeshare_source = 'eltdx'
                timeshare.extend(daily_points)
        except Exception:
            continue
    if not timeshare:
        # 退化：按缓存中已有的 1m / 5m / 15m / 30m bars 拼历史分时
        candidate_items: list[dict] = []
        for period in ('5m', '15m', '30m', '1m'):
            items, _ = bars_by_period.get(period, ([], None))
            if not items:
                continue
            distinct_dates = { _trade_date_from_item(it) for it in items if _trade_date_from_item(it) }
            if len(distinct_dates) >= 2:
                candidate_items = items
                break
        if not candidate_items:
            for period in ('1m', '5m', '15m', '30m'):
                items, _ = bars_by_period.get(period, ([], None))
                if items:
                    candidate_items = items
                    break
        per_date_timeshare: list[dict] = []
        for date_key in timeshare_trade_dates:
            day_items = [it for it in candidate_items if _trade_date_from_item(it) == date_key]
            if not day_items:
                continue
            per_date_timeshare.extend(build_intraday_timeshare(day_items))
        if not per_date_timeshare:
            per_date_timeshare = build_intraday_timeshare(candidate_items)
        timeshare = per_date_timeshare
        timeshare_source = primary_source


    snapshot = {
        'trade_date': resolved_trade_date,
        'requested_trade_date': requested_trade_date,
        'effective_adjust': minute_adjust,
        'requested_adjust': adjust,
        'timeshare': timeshare,
        'minute_bars': minute_bars_payload,
        'period_sources': {**period_sources, 'timeshare': timeshare_source},
        'requested_periods': requested_periods,
    }
    if resolved_trade_date:
        write_json_file(stock_intraday_cache_file(target_type, symbol, resolved_trade_date), {
            **snapshot,
            'symbol': symbol,
            'target_type': target_type,
            'source': source,
            'updated_at': datetime.now().isoformat(),
        })
    return snapshot, source
