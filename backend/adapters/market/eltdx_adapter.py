from dataclasses import asdict
from datetime import date, datetime

from eltdx import TdxClient

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


def stock_symbol_to_eltdx_code(symbol: str) -> str:
    return f'sh{symbol}' if symbol.startswith(('5', '6', '9')) else f'sz{symbol}'


def _get_hosts() -> list[str]:
    config_data = get_stock_chart_config().get('kline', {})
    mootdx_config = config_data.get('mootdx', {}) if isinstance(config_data, dict) else {}
    servers = mootdx_config.get('servers') or []
    return [f'{host}:{port}' for host, port in servers if host and port]


def _build_client() -> TdxClient:
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
