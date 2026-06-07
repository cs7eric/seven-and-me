"""继续探 881289 / 881087: 试 200743 看看 eltdx 自己怎么标 sector code."""
import sys
sys.path.insert(0, ".")
import eltdx

# 用 600519 (贵州茅台) 试 200743 拿相关板块, 看看 881289 / 881087 会不会出现
SEED = "sh600519"
with eltdx.TdxClient(pool_size=4, timeout=8.0) as client:
    client.connect()

    print(f"=== theme_market({SEED}, '200743') 相关板块 ===")
    try:
        f10 = client.f10
        resp = f10.theme_market(SEED, req_id="200743", page_size=30)
        # 200743 table1: N001=市场 N002=板块代码 N003=板块名称 N004=涨幅% N005=涨停数
        for t in resp.tables or []:
            for r in t.rows[:25]:
                n002 = str(r.get("N002", ""))
                if n002 in ("881289", "881087"):
                    print(f"  *** 找到: N001={r.get('N001')} N002={n002} N003={r.get('N003')} N004={r.get('N004')} N005={r.get('N005')}")
        # 顺手打印前 10 行所有 N002
        print()
        print("  前 10 个相关板块:")
        for t in resp.tables or []:
            for r in t.rows[:10]:
                print(f"    N001={r.get('N001')} N002={r.get('N002')} N003={r.get('N003')} N004={r.get('N004')}% N005={r.get('N005')}")
    except Exception as e:
        print(f"  ERR: {e}")
