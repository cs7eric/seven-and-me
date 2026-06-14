from dataclasses import asdict
from datetime import date, datetime

try:
    from eltdx import TdxClient
except Exception:
    TdxClient = None

from backend.adapters.market.common import build_volume_ratio, parse_stock_trade_timestamp

from backend.services.stock.config_service import get_stock_chart_config


def _sanitize_jsonable(value):
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _sanitize_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_jsonable(item) for item in value]
    return value


def stock_symbol_to_eltdx_code(symbol: str, target_type: str | None = None) -> str:
    """给 eltdx TCP 客户端拼带交易所前缀的代码.

    规则:
      - target_type='index' 时按指数代码前缀严格判断:
          000xxx / 880xxx → 上交所 sh (上证指数 / 上证综指 / 中证系列)
          399xxx         → 深交所 sz (深证成指 / 创业板指)
      - 个股时按上市板判断:
          5/6/9 开头 → 沪市 sh
          其它      → 深市 sz
    """
    if target_type == 'index':
        if symbol.startswith(('000', '880')):
            return f'sh{symbol}'
        if symbol.startswith('399'):
            return f'sz{symbol}'
        # 兜底: 未知指数代码, 默认沪
        return f'sh{symbol}'
    return f'sh{symbol}' if symbol.startswith(('5', '6', '9')) else f'sz{symbol}'


def _get_hosts() -> list[str]:
    config_data = get_stock_chart_config().get('kline', {})
    mootdx_config = config_data.get('mootdx', {}) if isinstance(config_data, dict) else {}
    servers = mootdx_config.get('servers') or []
    return [f'{host}:{port}' for host, port in servers if host and port]


def _build_client() -> TdxClient:
    if TdxClient is None:
        raise ValueError('eltdx 未安装或当前 Python 环境不可用')
    hosts = _get_hosts()
    if hosts:
        return TdxClient(hosts=hosts)
    return TdxClient()


def _safe_trade_date(value: str | None) -> date:
    if value:
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except ValueError:
            pass
    return datetime.now().date()


def fetch_stock_auction_from_eltdx(symbol: str, trade_date: str | None = None) -> dict:
    full_code = stock_symbol_to_eltdx_code(symbol)
    trading_date = _safe_trade_date(trade_date)

    with _build_client() as client:
        quote = client.get_quote(full_code)[0]
        call_auction = client.get_call_auction(full_code)
        auction_0925 = client.get_auction_0925(symbol, trading_date.isoformat())

    quote_payload = _sanitize_jsonable(asdict(quote))
    auction_payload = _sanitize_jsonable(asdict(call_auction))
    auction_0925_payload = _sanitize_jsonable(asdict(auction_0925))

    points = auction_payload.get('points') or []
    opening_points = [point for point in points if str(point.get('time_label') or '') <= '09:25:00']
    closing_points = [point for point in points if str(point.get('time_label') or '') >= '14:57:00']

    return {
        'symbol': symbol,
        'full_code': full_code,
        'trade_date': trading_date.isoformat(),
        'quote': quote_payload,
        'auction0925': auction_0925_payload,
        'openingPoints': opening_points,
        'closingPoints': closing_points,
        'allPoints': points,
    }


def _extract_rows_from_response(response) -> list[dict]:
    if response is None:
        return []
    if isinstance(response, list):
        rows = response
    elif hasattr(response, 'items'):
        rows = getattr(response, 'items')
    elif hasattr(response, 'rows'):
        rows = getattr(response, 'rows')
    elif hasattr(response, 'points'):
        rows = getattr(response, 'points')
    else:
        rows = response

    if callable(rows):
        rows = rows()
    # eltdx MinuteSeries.points / TradePage.ticks 都是 tuple, 不是 list;
    # 之前 isinstance(list) 卡死了 → 明明有 240 个点却返回 0.
    if not isinstance(rows, (list, tuple)):
        return []

    extracted: list[dict] = []
    for row in rows:
        if isinstance(row, dict):
            extracted.append(_sanitize_jsonable(row))
            continue
        if hasattr(row, '__dataclass_fields__'):
            extracted.append(_sanitize_jsonable(asdict(row)))
            continue
        raw = getattr(row, '__dict__', None)
        if isinstance(raw, dict):
            extracted.append(_sanitize_jsonable(raw))
    return extracted


def _coerce_float(value) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _coerce_trade_time(row: dict) -> datetime | None:
    candidates = [
        row.get('datetime'),
        row.get('trade_time'),
        row.get('trade_datetime'),
        row.get('time'),
        row.get('date'),
        row.get('day'),
    ]
    for value in candidates:
        if value is None:
            continue
        # eltdx MinutePoint / TradeTick 解析后, 'time' 已经是 datetime 对象
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value.strip():
            try:
                return parse_stock_trade_timestamp(value.strip())
            except ValueError:
                continue
    return None


def _normalize_kline_rows(rows: list[dict]) -> list[dict]:
    items: list[dict] = []
    previous_volume = None
    volumes_window: list[float] = []

    for row in rows:
        trade_time = _coerce_trade_time(row)
        if not trade_time:
            continue
        volume = _coerce_float(
            row.get('volume')
            or row.get('vol')
            or row.get('matched_volume')
        )
        turnover = _coerce_float(
            row.get('turnover')
            or row.get('amount')
            or row.get('matched_amount')
            or row.get('matched_amount_estimated')
        )
        turnover_rate_raw = row.get('turnover_rate')
        turnover_rate = float(turnover_rate_raw) if isinstance(turnover_rate_raw, (int, float)) else None
        close_price = _coerce_float(row.get('close') if row.get('close') is not None else row.get('price'))
        open_price = _coerce_float(row.get('open') if row.get('open') is not None else close_price)
        high_price = _coerce_float(row.get('high') if row.get('high') is not None else max(open_price, close_price))
        low_price = _coerce_float(row.get('low') if row.get('low') is not None else min(open_price, close_price))
        volume_ratio = build_volume_ratio(volume, previous_volume, volumes_window)
        previous_volume = volume
        items.append({
            'timestamp': int(trade_time.timestamp() * 1000),
            'trade_date': trade_time.strftime('%Y-%m-%d'),
            'open': open_price,
            'close': close_price,
            'high': high_price,
            'low': low_price,
            'volume': volume,
            'turnover': turnover,
            'turnover_rate': turnover_rate,
            'volume_ratio': volume_ratio,
        })
    return items


def fetch_stock_history_timeshare_from_eltdx(symbol: str, trade_date: str, target_type: str | None = None) -> list[dict]:
    full_code = stock_symbol_to_eltdx_code(symbol, target_type=target_type)
    trading_date = _safe_trade_date(trade_date)
    if hasattr(trading_date, 'date'):
        trading_date_value = trading_date.date()
    else:
        trading_date_value = trading_date

    with _build_client() as client:
        rows = _call_client_variants(
            client,
            ['get_history_minute'],
            [
                ((full_code, trading_date_value), {}),
                ((full_code,), {'date': trading_date_value}),
                ((), {'code': full_code, 'date': trading_date_value}),
            ],
            raise_on_error=True,
        )

    points: list[dict] = []
    for row in rows:
        trade_time = _coerce_trade_time(row)
        if not trade_time:
            continue
        price = _coerce_float(row.get('price') if row.get('price') is not None else row.get('close'))
        avg_price = row.get('avg_price')
        if not isinstance(avg_price, (int, float)):
            avg_price = row.get('average_price')
        if not isinstance(avg_price, (int, float)):
            avg_price = row.get('avg')
        volume = _coerce_float(row.get('volume') or row.get('vol') or row.get('matched_volume'))
        turnover = _coerce_float(
            row.get('turnover')
            or row.get('amount')
            or row.get('matched_amount')
            or row.get('matched_amount_estimated')
        )
        turnover_rate = row.get('turnover_rate')
        points.append({
            'timestamp': int(trade_time.timestamp() * 1000),
            'trade_date': trade_time.strftime('%Y-%m-%d'),
            'time_label': trade_time.strftime('%H:%M'),
            'price': round(price, 4),
            'avg_price': round(float(avg_price), 4) if isinstance(avg_price, (int, float)) else None,
            'volume': volume,
            'turnover': turnover,
            'turnover_rate': float(turnover_rate) if isinstance(turnover_rate, (int, float)) else None,
        })

    if points:
        return points
    raise ValueError('eltdx 历史分时接口未返回有效数据')


def _call_client_variants(client: TdxClient, method_names: list[str], variants: list[tuple[tuple, dict]], raise_on_error: bool = False) -> list[dict]:
    last_error = None
    for method_name in method_names:
        method = getattr(client, method_name, None)
        if not callable(method):
            continue
        for args, kwargs in variants:
            try:
                response = method(*args, **kwargs)
                rows = _extract_rows_from_response(response)
                if rows:
                    return rows
            except Exception as exc:
                last_error = exc
                continue
    if raise_on_error and last_error is not None:
        raise last_error
    if last_error and raise_on_error is False:
        return []
    return []


def fetch_stock_klines_from_eltdx(
    target_type: str,
    symbol: str,
    period: str,
    adjust: str,
    trade_date: str | None = None,
) -> list[dict]:
    if target_type == 'sector':
        raise ValueError('eltdx 暂不支持板块分钟K线')

    full_code = stock_symbol_to_eltdx_code(symbol, target_type=target_type)
    requested_trade_date = _safe_trade_date(trade_date).isoformat() if period == '1m' else None
    with _build_client() as client:
        rows: list[dict] = []
        if period == '1m':
            # 关键顺序: trade_date 给定时, get_history_minute 必须先于 get_minute.
            # get_minute(('sh000001',), {}) 永远返"今日" MinuteSeries (time=None),
            # 会被 _coerce_trade_time 过滤掉, normalize 出来 0 行;
            # 但 _call_client_variants 一旦看到 _extract_rows_from_response 返回非空
            # (240 行字典) 就停, 后面的 get_history_minute(history) 不会再试.
            minute_variants = [
                ((full_code, requested_trade_date), {}),
                ((), {'code': full_code, 'trade_date': requested_trade_date}),
                ((full_code,), {}),
                ((), {'code': full_code}),
                ((), {'symbol': full_code}),
                ((), {'symbol': full_code, 'trade_date': requested_trade_date}),
            ]
            methods = ['get_history_minute', 'get_minute'] if requested_trade_date else ['get_minute', 'get_history_minute']
            rows = _call_client_variants(client, methods, minute_variants)
        else:
            kline_variants = [
                ((full_code, period), {}),
                ((), {'code': full_code, 'period': period}),
                ((), {'symbol': full_code, 'period': period}),
                ((), {'code': full_code, 'frequency': period}),
                ((), {'symbol': full_code, 'frequency': period}),
            ]
            rows = _call_client_variants(client, ['get_kline_all', 'get_kline', 'get_minute', 'get_history_minute'], kline_variants)

    items = _normalize_kline_rows(rows)
    if items:
        return items
    raise ValueError('eltdx K线接口未返回有效数据')
