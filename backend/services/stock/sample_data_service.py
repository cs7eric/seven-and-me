from datetime import datetime, timedelta


def sample_stock_klines(symbol: str, period: str) -> list[dict]:
    base = 10.0 if symbol != '000300' else 3500.0
    today = datetime.now()
    period_minutes_map = {
        '1m': 1,
        '5m': 5,
        '15m': 15,
        '30m': 30,
        '60m': 60,
        '120m': 120,
    }
    minute_span = period_minutes_map.get(period)
    bars = []
    if minute_span is not None:
        start = today.replace(hour=9, minute=30, second=0, microsecond=0) - timedelta(minutes=minute_span * 119)
        for index in range(120):
            trade_time = start + timedelta(minutes=index * minute_span)
            drift = index * (0.03 if symbol != '000300' else 1.1)
            open_price = round(base + drift + ((index % 5) - 2) * 0.08, 2)
            close_price = round(open_price + ((index % 7) - 3) * 0.05, 2)
            high_price = round(max(open_price, close_price) + 0.09, 2)
            low_price = round(min(open_price, close_price) - 0.07, 2)
            volume = float(50000 + index * 1200)
            turnover = float(volume * max(close_price, 1))
            bars.append({
                'timestamp': int(trade_time.timestamp() * 1000),
                'open': open_price,
                'high': high_price,
                'low': low_price,
                'close': close_price,
                'volume': volume,
                'turnover': turnover,
                'volume_ratio': round(1 + (index % 10) * 0.08, 2),
            })
        return bars

    interval = 7 if period == '1w' else 1
    today_date = today.date()
    for index in range(120):
        trade_date = today_date - timedelta(days=(119 - index) * interval)
        drift = index * (0.08 if symbol != '000300' else 3.2)
        open_price = round(base + drift + ((index % 5) - 2) * 0.12, 2)
        close_price = round(open_price + ((index % 7) - 3) * 0.09, 2)
        high_price = round(max(open_price, close_price) + 0.18, 2)
        low_price = round(min(open_price, close_price) - 0.16, 2)
        volume = float(800000 + index * 6000)
        turnover = float(volume * max(close_price, 1))
        bars.append({
            'timestamp': int(datetime.combine(trade_date, datetime.min.time()).timestamp() * 1000),
            'open': open_price,
            'high': high_price,
            'low': low_price,
            'close': close_price,
            'volume': volume,
            'turnover': turnover,
            'volume_ratio': round(1 + (index % 10) * 0.14, 2),
        })
    return bars
