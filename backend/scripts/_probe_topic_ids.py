"""探 f10.topic_ids() 返回的 topic 字段 (有 industry / sslb 等元数据?)."""
import sys, json
sys.path.insert(0, ".")
import eltdx

with eltdx.TdxClient(pool_size=4, timeout=8.0) as client:
    client.connect()

    for code in ["sh600519", "sh688981", "sz000001", "bj920002", "sh688809"]:
        print(f"=== {code} f10.topic_ids ===")
        try:
            f10 = client.f10
            resp = f10.topic_ids(code)
            rows = resp.rows
            print(f"  total rows: {len(rows)}")
            for r in rows[:5]:
                print(f"    {json.dumps(r, ensure_ascii=False, default=str)}")
            # 找所有 key
            keys = set()
            for r in rows:
                keys.update(r.keys())
            print(f"  all keys: {sorted(keys)}")
        except Exception as e:
            print(f"  ERR: {e}")
        print()
