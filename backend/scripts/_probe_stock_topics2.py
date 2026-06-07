"""探 eltdx helpers.stock_topics 返回的 StockTopic 字段 (用 dataclasses.asdict)."""
import sys, json
sys.path.insert(0, ".")
import eltdx
from dataclasses import asdict

with eltdx.TdxClient(pool_size=4, timeout=8.0) as client:
    client.connect()

    for code in ["sh600519", "sh688819", "sh688981", "sz000001", "bj920002"]:
        print(f"=== {code} helpers.stock_topics ===")
        try:
            res = client.helpers.stock_topics(code)
            topics = getattr(res, "topics", []) or []
            print(f"  total topics: {len(topics)}")
            # 按 category_raw 分组看数量
            by_cr = {}
            for t in topics:
                cr = t.category_raw
                by_cr.setdefault(cr, []).append(t)
            for cr in sorted(by_cr.keys(), key=lambda x: (x is None, x)):
                cnt = len(by_cr[cr])
                print(f"  category_raw={cr}: {cnt} topics")
                # 每个 cat 打印前 2 个
                for t in by_cr[cr][:2]:
                    d = asdict(t)
                    # 截短 raw / reason
                    for k in list(d.keys()):
                        v = d[k]
                        if isinstance(v, str) and len(v) > 80:
                            d[k] = v[:80] + "..."
                    print(f"    {json.dumps(d, ensure_ascii=False, default=str)}")
            print()
        except Exception as e:
            print(f"  ERR: {e}")
            print()
