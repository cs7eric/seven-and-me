"""探测 akshare 同花顺行业接口."""
import time
import akshare as ak

probes = [
    ("stock_board_industry_name_ths", "同花顺行业列表", {}),
    ("stock_board_industry_cons_ths", "同花顺行业成分股(按名)", {"symbol": "半导体"}),
    ("stock_board_cons_ths", "同花顺行业成分股(按 code)", {"symbol": "881121"}),
]
for fn, desc, kwargs in probes:
    try:
        f = getattr(ak, fn)
    except AttributeError:
        print(f"[miss] {fn}")
        continue
    t0 = time.time()
    try:
        df = f(**kwargs)
        dt = (time.time() - t0) * 1000
        rows = len(df) if df is not None else 0
        print(f"[ok ]  {fn:42s}  rows={rows:>5d}  {dt:>6.0f}ms  -- {desc}")
        print(f"       cols: {list(df.columns)[:14]}")
        if rows:
            print(f"       sample: {df.head(2).to_dict('records')}")
    except Exception as e:
        dt = (time.time() - t0) * 1000
        print(f"[err]  {fn:42s}  {dt:>6.0f}ms  -- {desc}\n       {str(e).splitlines()[0][:120]}")
