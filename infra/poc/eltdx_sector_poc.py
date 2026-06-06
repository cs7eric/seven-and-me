"""POC v5: eltdx 板块 / 行业 能力全探。

任务:
  1) 找 eltdx 能识别的板块指数代码 (sh880xxx / sz399xxx / ...)
  2) get_kline(kind="index") 真能拿到板块 K 线吗?
  3) quotes.list_by_category() 拿涨幅榜能用吗?
  4) helpers.topic_stocks / helpers.stock_topics (已经接好, 验证一遍)
"""
from __future__ import annotations

import json
import sys

from eltdx import TdxClient

print("=" * 70)
print("POC: eltdx 板块 / 行业 能力")
print("=" * 70)

# 1) 找板块指数代码
print("\n--- 1) 找板块指数代码 ---")
print("说明: 通达信板块指数代码格式有")
print("  - sh880xxx / sz880xxx    (申万行业)")
print("  - sh000xxx / sz399xxx    (上证 / 深证指数)")
print("  - 8803xx                 (申万一级 6 大类)")
print("  - 8804xx-8805xx          (申万二级 31 个)")
print("  - 8806xx-8809xx          (申万三级 100+ 个)")
print("我们从 eltdx 拿到的 1678 个指数代码里看有没有 '880' 开头的")

with TdxClient(timeout=3) as client:
    codes = client.get_index_codes_all()
    print(f"  总指数: {len(codes)}")
    # 看 code 格式
    sample = codes[:20] if isinstance(codes[0], str) else [c.full_code if hasattr(c, "full_code") else str(c) for c in codes[:20]]
    print(f"  前 20 个: {sample[:10]}")
    # 找 880 开头的
    board_codes = []
    for c in codes:
        s = c if isinstance(c, str) else (getattr(c, "full_code", None) or str(c))
        if "880" in s or "BK" in s or "申万" in s or "板块" in s:
            board_codes.append(s)
    print(f"  含 880/BK/板块 关键字的: {len(board_codes)}")
    for s in board_codes[:15]:
        print(f"    {s}")
    # sh880 / sz880 单独看
    sh880 = [s for s in board_codes if isinstance(s, str) and s.startswith("sh880")]
    sz880 = [s for s in board_codes if isinstance(s, str) and s.startswith("sz880")]
    print(f"  sh880 开头: {len(sh880)}, sz880 开头: {len(sz880)}")

# 2) 测 get_kline(kind="index") 拿板块 K 线
print("\n--- 2) get_kline(kind='index') 拿板块 K 线 ---")
# 几个常见的板块指数代码 (根据社区资料):
candidates = [
    "sh880301",  # 申万一级 农林牧渔
    "sh880302",  # 申万一级 基础化工
    "sh880303",  # 申万一级 钢铁
    "sh880304",  # 申万一级 有色金属
    "sh880305",  # 申万一级 电子
    "sh880306",  # 申万一级 家用电器
    "sh880307",  # 申万一级 食品饮料
    "sh880308",  # 申万一级 纺织服饰
    "sh880310",  # 申万一级 医药生物
    "sh880311",  # 申万一级 电力设备
    "sh880320",  # 申万一级 银行
    "sh880322",  # 申万一级 非银金融
    "sh880323",  # 申万一级 房地产
    "sh880330",  # 申万一级 计算机
    "sh880332",  # 申万一级 传媒
    "sh880334",  # 申万一级 通信
    "sh880340",  # 申万一级 公用事业
    "sh880350",  # 申万一级 交通运输
    "sh880360",  # 申万一级 建筑装饰
    "sh880370",  # 申万一级 机械设备
    "sh880380",  # 申万一级 煤炭
    "sh880381",  # 申万一级 石油石化
    "sh880382",  # 申万一级 美容护理
]
with TdxClient(timeout=3) as client:
    for code in candidates:
        try:
            series = client.get_kline("day", code, count=3, kind="index")
            bars = getattr(series, "bars", series)
            n = len(bars) if hasattr(bars, "__len__") else 0
            first = bars[0] if n > 0 else None
            close = getattr(first, "close", "?") if first else "?"
            time = getattr(first, "time", "?") if first else "?"
            print(f"  [OK] {code} bars={n} first: time={time} close={close}")
        except Exception as exc:
            print(f"  [ERR] {code} {type(exc).__name__}: {str(exc)[:80]}")

# 3) 测 quotes.list_by_category 拿涨幅榜
print("\n--- 3) quotes.list_by_category 拿涨幅榜 ---")
with TdxClient(timeout=3) as client:
    for category in ["沪深A股", "上证A股", "深证A股", "行业板块", "概念板块"]:
        try:
            page = client.quotes.list_by_category(category, sort_by="涨幅", count=5)
            rows = getattr(page, "items", page) or []
            print(f"  [OK] {category}: {len(rows)} 条, 前 3:")
            for r in rows[:3]:
                # r 可能是 dataclass, 找变化率字段
                if hasattr(r, "name"):
                    print(f"    {getattr(r, 'code', '?')} {r.name} 涨幅={getattr(r, 'change_pct', '?')}")
                else:
                    print(f"    {r}")
        except Exception as exc:
            print(f"  [ERR] {category} {type(exc).__name__}: {str(exc)[:80]}")

# 4) bars.get() alt
print("\n--- 4) client.bars.get() alt API ---")
with TdxClient(timeout=3) as client:
    if hasattr(client, "bars"):
        print(f"  client.bars 类型: {type(client.bars).__name__}")
        if hasattr(client.bars, "get"):
            try:
                # 试指数 K 线
                series = client.bars.get(kind="index", code="sh880307", ktype="day", count=3)
                bars = getattr(series, "bars", series)
                n = len(bars) if hasattr(bars, "__len__") else 0
                print(f"  [OK] bars.get(kind='index', code='sh880307') = {n} bars")
            except Exception as exc:
                print(f"  [ERR] bars.get: {type(exc).__name__}: {str(exc)[:120]}")
    else:
        print("  client.bars 不存在")

# 5) 列出 eltdx 实际能用的 quotes 方法
print("\n--- 5) eltdx 板块相关方法全集 ---")
with TdxClient(timeout=3) as client:
    if hasattr(client, "quotes"):
        q_methods = [m for m in dir(client.quotes) if not m.startswith("_")]
        print(f"  client.quotes 方法: {q_methods}")
    if hasattr(client, "helpers"):
        h_methods = [m for m in dir(client.helpers) if not m.startswith("_")]
        print(f"  client.helpers 方法: {h_methods}")
    if hasattr(client, "f10"):
        f_methods = [m for m in dir(client.f10) if not m.startswith("_")]
        print(f"  client.f10 方法: {f_methods}")
    if hasattr(client, "limits"):
        print(f"  client.limits 类型: {type(client.limits).__name__}")
        if hasattr(client.limits, "__dict__"):
            print(f"  client.limits 属性: {list(client.limits.__dict__.keys())}")

print("\n=== 跑完 ===")
