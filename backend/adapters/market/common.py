from datetime import datetime, timezone, timedelta

BEIJING_TZ = timezone(timedelta(hours=8))


def _to_beijing(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=BEIJING_TZ)
    return value.astimezone(BEIJING_TZ)


def parse_stock_trade_timestamp(value: str) -> datetime:
    """解析行情/分时里的时间字段，统一按“北京时间”返回带 tzinfo 的 datetime。

    - ``YYYY-MM-DDTHH:MM:SS`` / 带 ``Z`` 的 ISO 字符串 → 当 UTC，再转北京时间
    - ``YYYY-MM-DD HH:MM[:SS]`` 这种不带的 → 默认就是北京时间
    - ``YYYY-MM-DD`` → 当作北京时间 00:00
    """
    normalized = str(value).strip()
    if not normalized:
        raise ValueError('empty trade timestamp')
    iso_candidate = normalized.replace('Z', '+00:00') if normalized.endswith('Z') else normalized
    if 'T' in iso_candidate or normalized.endswith('Z'):
        try:
            parsed = datetime.fromisoformat(iso_candidate)
        except ValueError as exc:
            raise ValueError(f'Unsupported trade timestamp: {value}') from exc
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=BEIJING_TZ)
        return parsed.astimezone(BEIJING_TZ)

    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(normalized, fmt).replace(tzinfo=BEIJING_TZ)
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
