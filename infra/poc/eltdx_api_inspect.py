"""POC v6: 看 list_by_category / bars.get 的实际签名."""
import inspect
from eltdx import TdxClient

print("=" * 70)
print("eltdx 内部 API 签名探查")
print("=" * 70)

# 1) list_by_category 签名
print("\n--- 1) client.quotes.list_by_category() 签名 ---")
print(f"  signature: {inspect.signature(TdxClient.quotes.list_by_category)}")
print(f"  doc:")
doc = inspect.getdoc(TdxClient.quotes.list_by_category)
if doc:
    for line in doc.split("\n")[:30]:
        print(f"    {line}")

# 2) bars.get 签名
print("\n--- 2) client.bars.get() 签名 ---")
print(f"  signature: {inspect.signature(TdxClient.bars.get)}")
print(f"  doc:")
doc = inspect.getdoc(TdxClient.bars.get)
if doc:
    for line in doc.split("\n")[:30]:
        print(f"    {line}")

# 3) 试不同数字 category 看 list_by_category 返回什么
print("\n--- 3) 试 list_by_category 的数字 category ---")
with TdxClient(timeout=3) as client:
    for cat in [0, 1, 2, 3, 4, 5, 6, 10, 20, 50, 100, 200, 201, 300, 301, 500]:
        try:
            page = client.quotes.list_by_category(cat, sort_by="涨幅", count=3)
            print(f"  [OK] cat={cat:4d} type={type(page).__name__}")
            attrs = [a for a in dir(page) if not a.startswith("_")]
            print(f"    attrs: {attrs[:8]}")
            items = getattr(page, "items", None) or getattr(page, "rows", None)
            if items:
                first = items[0]
                print(f"    first type: {type(first).__name__}")
                if hasattr(first, "code"):
                    print(f"    first: code={getattr(first, 'code', '?')} name={getattr(first, 'name', '?')} pct={getattr(first, 'change_pct', '?')}")
                else:
                    print(f"    first: {first}")
        except Exception as exc:
            print(f"  [ERR] cat={cat:4d} {type(exc).__name__}: {str(exc)[:80]}")

# 4) 看 f10.hot_topics 返回什么 (这个是已有的)
print("\n--- 4) client.f10.hot_topics() 验证 ---")
with TdxClient(timeout=3) as client:
    try:
        result = client.f10.hot_topics()
        print(f"  type: {type(result).__name__}")
        if isinstance(result, list):
            for h in result[:3]:
                print(f"    {h}")
        elif hasattr(result, "__dict__"):
            print(f"  {result.__dict__}")
        else:
            print(f"  {str(result)[:200]}")
    except Exception as exc:
        print(f"  [ERR] {type(exc).__name__}: {str(exc)[:80]}")

# 5) 拿真实板块名称映射
print("\n--- 5) 找 sh8803xx-8809xx 的中文名 ---")
with TdxClient(timeout=3) as client:
    codes = client.get_index_codes_all()
    print(f"  总指数: {len(codes)}")
    # 找 sh8803xx-8804xx 这些常见区间
    target_ranges = [
        ("sh8803", 31),  # 申万一级 (31 个)
        ("sh8804", 50),  # 申万二级 (50+)
        ("sh8805", 50),  # 申万三级
    ]
    for prefix, n in target_ranges:
        matched = [c for c in codes if isinstance(c, str) and c.startswith(prefix)]
        print(f"  {prefix}xx 开头: {len(matched)} 个")
        for s in matched[:n]:
            print(f"    {s}")

# 6) 拿一个板块的 quote 验证 list_by_category(category) 怎么用
print("\n--- 6) 找正确的 list_by_category 数字 category (从源) ---")
import eltdx
src = inspect.getsourcefile(TdxClient.quotes.list_by_category)
print(f"  源文件: {src}")
if src:
    with open(src, "r", encoding="utf-8") as f:
        text = f.read()
    # 找 CategoryKind / category 之类的常量
    for keyword in ["CategoryKind", "category", "Category ="]:
        idx = text.find(keyword)
        if idx > -1:
            print(f"\n  [ {keyword} ]:")
            for i, line in enumerate(text[idx:idx+500].split("\n")[:10]):
                print(f"    {line}")
