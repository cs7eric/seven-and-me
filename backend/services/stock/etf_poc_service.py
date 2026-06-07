from __future__ import annotations

from datetime import datetime
import html
import json
import logging
import re
import time
from typing import Any

import requests

from backend.adapters.market.eastmoney import (
    parse_eastmoney_kline_rows,
    stock_adjust_to_eastmoney_fqt,
    stock_period_to_eastmoney_klt,
)
from backend.adapters.market.tencent import fetch_stock_klines_from_tencent
from backend.config.settings import STOCK_EASTMONEY_HEADERS, STOCK_EASTMONEY_KLINE_URL
from backend.repositories.stock.workspace_repo import read_cached_stock_klines, stock_kline_cache_file
from backend.utils.json_io import write_json_file


ETF_QUOTE_URL = 'https://push2.eastmoney.com/api/qt/stock/get'
ETF_HOLDINGS_URL = 'https://fundf10.eastmoney.com/FundArchivesDatas.aspx'
logger = logging.getLogger(__name__)


def _clean_symbol(symbol: str) -> str:
    value = str(symbol or '').strip().lower()
    if value.startswith(('sh', 'sz')):
        value = value[2:]
    if not value:
        raise ValueError('ETF symbol 不能为空')
    return value


def _eastmoney_secid_for_etf(symbol: str) -> str:
    clean = _clean_symbol(symbol)
    market = '1' if clean.startswith(('5', '6', '9')) else '0'
    return f'{market}.{clean}'


def _eastmoney_secid_candidates_for_etf(symbol: str) -> list[str]:
    clean = _clean_symbol(symbol)
    primary_market = '1' if clean.startswith(('5', '6', '9')) else '0'
    secondary_market = '0' if primary_market == '1' else '1'
    return [f'{primary_market}.{clean}', f'{secondary_market}.{clean}']


def _safe_float(value: Any) -> float | None:
    if value in (None, '', '-', '--'):
        return None
    try:
        return float(str(value).replace(',', '').replace('%', '').strip())
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    number = _safe_float(value)
    if number is None:
        return None
    return int(number)


def _session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def fetch_etf_realtime_quote(symbol: str) -> dict[str, Any]:
    clean = _clean_symbol(symbol)
    started_at = time.perf_counter()
    response = _session().get(
        ETF_QUOTE_URL,
        params={
            'secid': _eastmoney_secid_for_etf(clean),
            'fields': 'f57,f58,f43,f44,f45,f46,f47,f48,f60,f86,f168,f169,f170',
            'ut': 'fa5fd1943c7b386f172d6893dbfba10b',
            'fltt': '2',
            'invt': '2',
        },
        headers=STOCK_EASTMONEY_HEADERS,
        timeout=(5, 12),
        proxies={'http': None, 'https': None},
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get('data') or {}
    if not data:
        raise ValueError(f'东方财富未返回 ETF 实时行情: {clean}')

    result = {
        'symbol': str(data.get('f57') or clean),
        'name': str(data.get('f58') or clean),
        'price': _safe_float(data.get('f43')),
        'open': _safe_float(data.get('f46')),
        'high': _safe_float(data.get('f44')),
        'low': _safe_float(data.get('f45')),
        'previous_close': _safe_float(data.get('f60')),
        'change': _safe_float(data.get('f169')),
        'change_pct': _safe_float(data.get('f170')),
        'volume': _safe_int(data.get('f47')),
        'turnover': _safe_float(data.get('f48')),
        'turnover_rate': _safe_float(data.get('f168')),
        'quote_timestamp': _safe_int(data.get('f86')),
        'source': 'eastmoney.quote',
    }
    logger.info(
        'etf quote symbol=%s name=%s price=%s change_pct=%s elapsed_ms=%.1f',
        clean,
        result.get('name'),
        result.get('price'),
        result.get('change_pct'),
        (time.perf_counter() - started_at) * 1000,
    )
    return result


def _enrich_kline_items(items: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    previous_close: float | None = None
    for item in sorted(items, key=lambda row: int(row.get('timestamp') or 0)):
        row = dict(item)
        close = _safe_float(row.get('close'))
        if close is not None and previous_close not in (None, 0):
            change = close - float(previous_close)
            row['change'] = round(change, 4)
            row['change_pct'] = round(change / float(previous_close) * 100, 4)
        else:
            row['change'] = None
            row['change_pct'] = None
        if close is not None:
            previous_close = close
        enriched.append(row)
    return enriched[-count:] if count > 0 else enriched


def _unique_adjusts(adjust: str) -> list[str]:
    values: list[str] = []
    for item in [adjust, 'none', 'qfq', 'hfq']:
        value = str(item or '').strip() or 'none'
        if value not in values:
            values.append(value)
    return values


def _fetch_etf_klines_from_eastmoney_direct(
    symbol: str,
    *,
    period: str,
    adjust: str,
    errors: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], str | None]:
    clean = _clean_symbol(symbol)
    params = {
        'fields1': 'f1,f2,f3,f4,f5,f6',
        'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
        'ut': 'fa5fd1943c7b386f172d6893dbfba10b',
        'klt': stock_period_to_eastmoney_klt(period),
        'beg': '20180101',
        'end': '20500101',
        'lmt': '500',
    }
    session = _session()
    for secid in _eastmoney_secid_candidates_for_etf(clean):
        for candidate_adjust in _unique_adjusts(adjust):
            fqt = stock_adjust_to_eastmoney_fqt(candidate_adjust)
            try:
                response = session.get(
                    STOCK_EASTMONEY_KLINE_URL,
                    params={**params, 'secid': secid, 'fqt': fqt},
                    headers=STOCK_EASTMONEY_HEADERS,
                    timeout=(5, 12),
                    proxies={'http': None, 'https': None},
                )
                response.raise_for_status()
                payload = response.json()
                data = payload.get('data') or {}
                rows = data.get('klines') or []
                items = parse_eastmoney_kline_rows(rows)
                if items:
                    return items, f'eastmoney.kline:{secid}:adjust={candidate_adjust}'
                errors.append({
                    'provider': 'eastmoney.kline',
                    'secid': secid,
                    'adjust': candidate_adjust,
                    'error': 'empty klines',
                })
            except Exception as exc:
                errors.append({
                    'provider': 'eastmoney.kline',
                    'secid': secid,
                    'adjust': candidate_adjust,
                    'error': str(exc),
                })
    return [], None


def fetch_etf_klines(
    symbol: str,
    *,
    period: str = '1d',
    adjust: str = 'qfq',
    count: int = 120,
) -> dict[str, Any]:
    clean = _clean_symbol(symbol)
    started_at = time.perf_counter()
    errors: list[dict[str, str]] = []
    items, source = _fetch_etf_klines_from_eastmoney_direct(
        clean,
        period=period,
        adjust=adjust,
        errors=errors,
    )

    if not items:
        for candidate_adjust in _unique_adjusts(adjust):
            try:
                items = fetch_stock_klines_from_tencent('etf', clean, period, candidate_adjust)
                source = f'tencent.kline:adjust={candidate_adjust}'
                break
            except Exception as exc:
                errors.append({
                    'provider': 'tencent.kline',
                    'adjust': candidate_adjust,
                    'error': str(exc),
                })

    if not items:
        for candidate_adjust in _unique_adjusts(adjust):
            cached_items = read_cached_stock_klines('etf', clean, period, candidate_adjust)
            if cached_items:
                items = cached_items
                source = f'cache:adjust={candidate_adjust}'
                break

    if not source:
        source = 'none'

    items = _enrich_kline_items(items, count)
    logger.info(
        'etf kline symbol=%s period=%s adjust=%s source=%s count=%s errors=%s elapsed_ms=%.1f',
        clean,
        period,
        adjust,
        source,
        len(items),
        len(errors),
        (time.perf_counter() - started_at) * 1000,
    )
    if source.startswith(('eastmoney.kline', 'tencent.kline')) and items:
        write_json_file(stock_kline_cache_file('etf', clean, period, adjust), {
            'symbol': clean,
            'target_type': 'etf',
            'period': period,
            'adjust': adjust,
            'updated_at': datetime.now().isoformat(),
            'source': source,
            'items': items,
        })

    return {
        'symbol': clean,
        'target_type': 'etf',
        'period': period,
        'adjust': adjust,
        'count': len(items),
        'items': items,
        'source': source,
        'eastmoney_klt': stock_period_to_eastmoney_klt(period),
        'eastmoney_fqt': stock_adjust_to_eastmoney_fqt(adjust),
        'errors': errors[-12:],
        'upstream_url': STOCK_EASTMONEY_KLINE_URL,
    }


def _decode_js_string(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except Exception:
        return value.replace('\\/', '/')


def _strip_tags(value: str) -> str:
    no_tags = re.sub(r'<[^>]+>', '', value)
    return html.unescape(no_tags).replace('\xa0', ' ').strip()


def _extract_holdings_content(text: str) -> str:
    match = re.search(r'content\s*:\s*"(?P<content>.*?)"\s*,\s*arryear', text, flags=re.S)
    if not match:
        match = re.search(r'"content"\s*:\s*"(?P<content>.*?)"\s*,\s*"arryear"', text, flags=re.S)
    if not match:
        raise ValueError('东方财富基金持仓接口未返回 content 字段')
    return _decode_js_string(match.group('content'))


def _extract_report_date(content: str) -> str | None:
    candidates = re.findall(r'(\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{1,2}-\d{1,2})', content)
    return candidates[0] if candidates else None


def _parse_holding_rows(content: str, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', content, flags=re.S | re.I):
        cells = [_strip_tags(cell) for cell in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, flags=re.S | re.I)]
        if len(cells) < 4:
            continue
        code_idx = next((idx for idx, cell in enumerate(cells) if re.fullmatch(r'\d{6}', cell)), None)
        if code_idx is None:
            continue
        rank = _safe_int(cells[0])
        code = cells[code_idx]
        name = cells[code_idx + 1] if code_idx + 1 < len(cells) else ''
        ratio = next((_safe_float(cell) for cell in cells if '%' in cell), None)
        rows.append({
            'rank': rank or len(rows) + 1,
            'stock_code': code,
            'stock_name': name,
            'net_value_ratio': ratio,
            'raw_cells': cells,
        })
        if len(rows) >= limit:
            break
    return rows


def fetch_etf_holdings(symbol: str, *, limit: int = 20) -> dict[str, Any]:
    clean = _clean_symbol(symbol)
    started_at = time.perf_counter()
    response = _session().get(
        ETF_HOLDINGS_URL,
        params={
            'type': 'jjcc',
            'code': clean,
            'topline': str(max(1, min(limit, 100))),
            'year': '',
            'month': '',
        },
        headers={
            **STOCK_EASTMONEY_HEADERS,
            'Accept': '*/*',
            'Referer': f'https://fundf10.eastmoney.com/ccmx_{clean}.html',
        },
        timeout=(5, 15),
        proxies={'http': None, 'https': None},
    )
    response.raise_for_status()
    content = _extract_holdings_content(response.text)
    rows = _parse_holding_rows(content, limit)
    result = {
        'symbol': clean,
        'items': rows,
        'count': len(rows),
        'report_date': _extract_report_date(content),
        'source': 'eastmoney.fundf10.holdings',
        'note': '公开基金持仓通常按定期报告披露，可用于 POC；不是 ETF 每日 PCF 清单。',
    }
    logger.info(
        'etf holdings symbol=%s count=%s report_date=%s elapsed_ms=%.1f',
        clean,
        len(rows),
        result.get('report_date'),
        (time.perf_counter() - started_at) * 1000,
    )
    return result


def build_etf_poc(
    symbol: str,
    *,
    period: str = '1d',
    adjust: str = 'qfq',
    kline_count: int = 120,
    holdings_limit: int = 20,
) -> dict[str, Any]:
    clean = _clean_symbol(symbol)
    started_at = time.perf_counter()
    errors: list[dict[str, str]] = []

    quote: dict[str, Any] | None = None
    try:
        quote = fetch_etf_realtime_quote(clean)
    except Exception as exc:
        logger.exception('etf quote failed symbol=%s: %s', clean, exc)
        errors.append({'section': 'quote', 'error': str(exc)})

    kline = fetch_etf_klines(clean, period=period, adjust=adjust, count=kline_count)
    latest_bar = kline['items'][-1] if kline.get('items') else None
    if not latest_bar:
        errors.append({'section': 'kline', 'error': '未获取到 ETF K 线'})

    holdings: dict[str, Any] | None = None
    try:
        holdings = fetch_etf_holdings(clean, limit=holdings_limit)
    except Exception as exc:
        logger.exception('etf holdings failed symbol=%s: %s', clean, exc)
        errors.append({'section': 'holdings', 'error': str(exc)})
        holdings = {
            'symbol': clean,
            'items': [],
            'count': 0,
            'source': 'none',
            'note': '成分股/持仓接口暂不可用',
        }

    summary = {
        'symbol': clean,
        'name': (quote or {}).get('name') or clean,
        'price': (quote or {}).get('price') if quote else (latest_bar or {}).get('close'),
        'change': (quote or {}).get('change') if quote else (latest_bar or {}).get('change'),
        'change_pct': (quote or {}).get('change_pct') if quote else (latest_bar or {}).get('change_pct'),
        'volume': (quote or {}).get('volume') if quote else (latest_bar or {}).get('volume'),
        'turnover': (quote or {}).get('turnover') if quote else (latest_bar or {}).get('turnover'),
        'turnover_rate': (quote or {}).get('turnover_rate') if quote else (latest_bar or {}).get('turnover_rate'),
        'trade_date': (latest_bar or {}).get('trade_date'),
    }

    result = {
        'ok': not errors or bool(kline.get('items') or (holdings or {}).get('items') or quote),
        'target_type': 'etf',
        'symbol': clean,
        'summary': summary,
        'quote': quote,
        'kline': kline,
        'holdings': holdings,
        'errors': errors,
        'fetched_at': datetime.now().isoformat(),
    }
    logger.info(
        'etf poc done symbol=%s ok=%s kline_count=%s holdings_count=%s errors=%s elapsed_ms=%.1f',
        clean,
        result.get('ok'),
        (kline or {}).get('count'),
        (holdings or {}).get('count'),
        len(errors),
        (time.perf_counter() - started_at) * 1000,
    )
    return result
