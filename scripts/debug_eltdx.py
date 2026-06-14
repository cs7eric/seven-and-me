"""一次性 debug: 跟踪 eltdx 1m K 拉取链, 找出哪个 variant 失败 / 为啥 normalize 出来是空."""
import sys
sys.path.insert(0, '.')

from datetime import date
from eltdx import TdxClient
from backend.adapters.market.eltdx_adapter import (
    _extract_rows_from_response, _normalize_kline_rows, stock_symbol_to_eltdx_code,
    _call_client_variants,
)

full = stock_symbol_to_eltdx_code('000001', target_type='index')
print('full_code:', full)
requested_trade_date = '2026-05-25'
trading_date_value = date(2026, 5, 25)

with TdxClient() as c:
    print('--- get_history_minute (positional) ---')
    try:
        r = c.get_history_minute(full, trading_date_value)
        print('type:', type(r).__name__, 'count:', getattr(r, 'count', None))
        rows = _extract_rows_from_response(r)
        print('extracted rows:', len(rows))
        items = _normalize_kline_rows(rows)
        print('normalized items:', len(items))
        if items:
            print('first:', items[0])
        else:
            # 看 rows 第一个长啥样
            if rows:
                print('first row:', rows[0])
    except Exception as e:
        print('FAIL:', e)

    # 看 _call_client_variants 内部走的哪个
    print()
    print('--- _call_client_variants 跟日志 ---')
    minute_variants = [
        ((full,), {}),
        ((), {'code': full}),
        ((), {'symbol': full}),
        ((full, requested_trade_date), {}),
        ((), {'code': full, 'trade_date': requested_trade_date}),
        ((), {'symbol': full, 'trade_date': requested_trade_date}),
    ]
    for i, (args, kwargs) in enumerate(minute_variants):
        for method_name in ['get_minute', 'get_history_minute']:
            method = getattr(c, method_name, None)
            if not callable(method):
                continue
            try:
                if args and kwargs:
                    response = method(*args, **kwargs)
                elif args:
                    response = method(*args)
                elif kwargs:
                    response = method(**kwargs)
                else:
                    continue
                # 找到第一个有数据的
                rows = _extract_rows_from_response(response)
                if rows:
                    print(f'  v{i+1} {method_name}({args!r}, {kwargs!r}) → {len(rows)} rows')
                    print(f'    first row: {rows[0]}')
                    items = _normalize_kline_rows(rows)
                    print(f'    normalized: {len(items)} items')
                    if items:
                        print(f'    first item: {items[0]}')
                    break
                else:
                    print(f'  v{i+1} {method_name}({args!r}, {kwargs!r}) → 0 rows, response type={type(response).__name__}')
                    if hasattr(response, '__dataclass_fields__'):
                        from dataclasses import asdict
                        d = asdict(response)
                        print(f'    has .points?', 'points' in d, 'len(points)=', len(d.get('points') or []))
            except Exception as e:
                print(f'  v{i+1} {method_name}({args!r}, {kwargs!r}) → EXC: {e}')
