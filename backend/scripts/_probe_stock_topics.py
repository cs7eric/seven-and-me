"""直接探 eltdx helpers.stock_topics 返回数据的完整字段."""
import sys, json
sys.path.insert(0, ".")
import eltdx

with eltdx.TdxClient(pool_size=4, timeout=8.0) as client:
    client.connect()

    for code in ["sh600519", "sh688819", "sh688981", "sz000001"]:
        print(f"=== {code} helpers.stock_topics ===")
        try:
            res = client.helpers.stock_topics(code)
            topics = getattr(res, "topics", []) or []
            print(f"  total topics: {len(topics)}")
            if topics:
                # 第一个 topic 的所有字段
                print(f"  topic[0] keys: {list(topics[0].__dict__.keys()) if hasattr(topics[0], '__dict__') else dir(topics[0])}")
                t0 = topics[0]
                if hasattr(t0, "__dict__"):
                    print(f"  topic[0] dict: {json.dumps(t0.__dict__, ensure_ascii=False, default=str)}")
                # 找 category_raw == 0 的 topic
                for t in topics:
                    cr = t.category_raw if hasattr(t, "category_raw") else None
                    if cr == 0:
                        print(f"  cat=0 topic: {json.dumps(t.__dict__, ensure_ascii=False, default=str)}")
                        break
                # 也打印 cat=2 和 cat=4 各一个
                seen_cr = set()
                for t in topics:
                    cr = t.category_raw if hasattr(t, "category_raw") else None
                    if cr not in seen_cr and cr is not None:
                        seen_cr.add(cr)
                        print(f"  cat={cr} topic sample: {json.dumps(t.__dict__, ensure_ascii=False, default=str)}")
                        if len(seen_cr) >= 3:
                            break
        except Exception as e:
            print(f"  ERR: {e}")
        print()
