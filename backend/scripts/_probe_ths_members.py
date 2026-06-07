"""探测 akshare 同花顺行业个股 / 摘要接口."""
import time
import akshare as ak

probes = [
    ("stock_board_industry_index_ths", "同花顺行业指数实时", {"symbol": "半导体"}),
    ("stock_board_industry_summary_ths", "同花顺行业摘要", {"symbol": "半导体"}),
    ("stock_board_industry_info_ths", "同花顺行业信息(成分?)", {"symbol": "半导体"}),
    ("stock_board_industry_summary_ths", "同花顺行业摘要(code)", {"symbol": "881121"}),
    ("stock_board_industry_info_ths", "同花顺行业信息(code)", {"symbol": "881121"}),
    ("stock_concept_cons_futu", "富途概念成分股", {"symbol": "半导体"}),
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
        print(f"[ok ]  {fn:38s} {str(kwargs)[:24]:24s}  rows={rows:>5d}  {dt:>6.0f}ms  -- {desc}")
        print(f"       cols: {list(df.columns)[:14]}")
        if rows:
            print(f"       sample: {df.head(2).to_dict('records')}")
    except Exception as e:
        dt = (time.time() - t0) * 1000
        print(f"[err]  {fn:38s} {dt:>6.0f}ms  -- {desc}\n       {str(e).splitlines()[0][:120]}")
