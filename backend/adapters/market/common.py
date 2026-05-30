from datetime import datetime


def parse_stock_trade_timestamp(value: str) -> datetime:
    normalized = str(value).strip()
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    raise ValueError(f'Unsupported trade timestamp: {value}')


def build_volume_ratio(volume: float, previous_volume: float | None, volumes_window: list[float]) -> float:
    volumes_window.append(volume)
    recent_window = volumes_window[-5:]
    base_avg = sum(recent_window[:-1]) / max(len(recent_window) - 1, 1) if len(recent_window) > 1 else 0
    if base_avg > 0:
        return round(volume / base_avg, 2)
    if previous_volume and previous_volume > 0:
        return round(volume / previous_volume, 2)
    return 1.0
