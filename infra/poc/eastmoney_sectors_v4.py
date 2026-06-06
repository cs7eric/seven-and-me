"""POC v4: 系统探 Eastmoney + eltdx 在 板块 / 行业 / 涨跌 / K 线 维度的能力。

把超时拉长到 10s，push2 / push2his 都重试。
"""
from __future__ import annotations

import json
import os
from typing import Any

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://quote.eastmoney.com/",
    "Origin": "https://quote.eastmoney.com",
}


def fetch(url: str, params: dict[str, Any] | None = None, timeout: int = 10) -> dict[str, Any] | None:
    """绕代理."""
    proxy_keys = ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]
    backup = {k: os.environ.get(k) for k in proxy_keys}
    for k in proxy_keys:
        os.environ.pop(k, None)
    try:
        s = requests.Session()
        s.trust_env = False
        r = s.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=(5, timeout),
            proxies={"http": None, "https": None},
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return None
    finally:
        for k, v in backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def preview(label: str, data: Any) -> None:
    print(f"--- {label} ---")
    if data is None:
        print("  [X] 网络错 / 超时")
        return
    if isinstance(data, dict):
        # push2 响应: {rc, rt, svr, lt, full, dlmkts, data: {total, diff, ...}}
        if "data" in data and isinstance(data["data"], dict):
            d = data["data"]
            total = d.get("total")
            diff = d.get("diff") or d.get("klines") or []
            print(f"  rc={data.get('rc')} total={total} 返回 {len(diff) if isinstance(diff, list) else '?'} 条")
            if isinstance(diff, list):
                for row in diff[:3]:
                    print(f"    {json.dumps(row, ensure_ascii=False)[:180]}")
            return
        if "data" in data and isinstance(data["data"], list):
            print(f"  data 是 list, {len(data['data'])} 条")
            for row in data["data"][:3]:
                print(f"    {json.dumps(row, ensure_ascii=False)[:180]}")
            return
        # 错误响应
        print(f"  {json.dumps(data, ensure_ascii=False)[:200]}")
    else:
        print(f"  {str(data)[:200]}")


# =============================================================================
# 1) push2 /api/qt/clist/get — 板块成分股
# =============================================================================
print("=" * 70)
print("1) push2 clist - 板块成分股 / 全量列表")
print("=" * 70)

# 1.1 BK0438 食品饮料 成分股
preview("1.1 push2 clist fs=b:BK0438 (BK0438 食品饮料 成分股)", fetch(
    "http://push2.eastmoney.com/api/qt/clist/get",
    {
        "pn": 1, "pz": 5, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "b:BK0438",
        "fields": "f1,f2,f3,f4,f5,f6,f12,f14,f104,f105",
    },
    timeout=10,
))

# 1.2 申万一级 m:90+t:1
preview("1.2 push2 clist fs=m:90+t:1 (申万一级行业)", fetch(
    "http://push2.eastmoney.com/api/qt/clist/get",
    {
        "pn": 1, "pz": 5, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "m:90+t:1",
        "fields": "f1,f2,f3,f4,f12,f14",
    },
    timeout=10,
))

# 1.3 概念 m:90+t:4
preview("1.3 push2 clist fs=m:90+t:4 (概念板块)", fetch(
    "http://push2.eastmoney.com/api/qt/clist/get",
    {
        "pn": 1, "pz": 5, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "m:90+t:4",
        "fields": "f1,f2,f3,f4,f12,f14",
    },
    timeout=10,
))

# 1.4 沪深京 A 股全量 (m:0+t:6+m:0+t:13+m:0+t:80+m:1+t:2+m:1+t:23)
preview("1.4 push2 clist fs=沪深京A (全量股票列表)", fetch(
    "http://push2.eastmoney.com/api/qt/clist/get",
    {
        "pn": 1, "pz": 5, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f1,f2,f3,f4,f12,f14",
    },
    timeout=10,
))

# =============================================================================
# 2) push2 /api/qt/stock/kline/get — 板块 K 线
# =============================================================================
print()
print("=" * 70)
print("2) push2 stock/kline/get - 板块 K 线")
print("=" * 70)

# 2.1 BK0438 日 K 线 (secid 格式: 1.BK0438 沪深板块)
preview("2.1 push2 kline secid=1.BK0438 日 K", fetch(
    "http://push2.eastmoney.com/api/qt/stock/kline/get",
    {
        "secid": "1.BK0438",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "1",
        "beg": "0",
        "end": "20500101",
        "lmt": "5",
    },
    timeout=10,
))

# 2.2 BK0438 5 分钟 K 线
preview("2.2 push2 kline secid=1.BK0438 5分钟 K", fetch(
    "http://push2.eastmoney.com/api/qt/stock/kline/get",
    {
        "secid": "1.BK0438",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "klt": "5",
        "fqt": "1",
        "beg": "0",
        "end": "20500101",
        "lmt": "3",
    },
    timeout=10,
))

# 2.3 沪深300 指数 K 线 (1.000300)
preview("2.3 push2 kline secid=1.000300 沪深300 日 K", fetch(
    "http://push2.eastmoney.com/api/qt/stock/kline/get",
    {
        "secid": "1.000300",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "1",
        "beg": "0",
        "end": "20500101",
        "lmt": "3",
    },
    timeout=10,
))

# 2.4 深证成指 secid=0.399001
preview("2.4 push2 kline secid=0.399001 深证成指 日 K", fetch(
    "http://push2.eastmoney.com/api/qt/stock/kline/get",
    {
        "secid": "0.399001",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "1",
        "beg": "0",
        "end": "20500101",
        "lmt": "3",
    },
    timeout=10,
))

# =============================================================================
# 3) 板块涨跌 (实时 + 历史)
# =============================================================================
print()
print("=" * 70)
print("3) 板块涨跌 (实时 / 历史)")
print("=" * 70)

# 3.1 BK0438 实时行情 (含涨跌幅 f3)
preview("3.1 BK0438 实时 (按涨跌幅排序)", fetch(
    "http://push2.eastmoney.com/api/qt/clist/get",
    {
        "pn": 1, "pz": 5, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "b:BK0438",
        "fields": "f1,f2,f3,f4,f5,f6,f7,f12,f14,f104,f105,f128",
    },
    timeout=10,
))

# 3.2 申万二级 按涨跌幅排行
preview("3.2 申万二级行业按涨跌幅排行", fetch(
    "http://push2.eastmoney.com/api/qt/clist/get",
    {
        "pn": 1, "pz": 10, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "m:90+t:2",
        "fields": "f1,f2,f3,f4,f5,f6,f12,f14",
    },
    timeout=10,
))

# =============================================================================
# 4) eltdx 实测 - 板块 / 行业 K 线 / 涨跌停
# =============================================================================
print()
print("=" * 70)
print("4) eltdx 实测")
print("=" * 70)

import eltdx

# 4.1 指数代码全集
try:
    with eltdx.TdxClient() as client:
        index_codes = client.get_index_codes_all()
        print(f"--- 4.1 eltdx get_index_codes_all(): {len(index_codes)} 个指数 ---")
        for c in index_codes[:3]:
            print(f"  {c.full_code} {c.name}")
        # 看看有没有 BK code 格式的指数 (板块)
        bk_codes = [c for c in index_codes if "BK" in c.full_code or "板块" in c.name or "行业" in c.name]
        print(f"  含 BK/板块/行业 关键字的指数: {len(bk_codes)}")
        for c in bk_codes[:5]:
            print(f"    {c.full_code} {c.name}")
except Exception as exc:
    print(f"--- 4.1 eltdx get_index_codes_all 失败: {exc} ---")

# 4.2 板块 K 线 (用 BK0438 试)
try:
    with eltdx.TdxClient() as client:
        # 先用 get_kline 试 BK0438
        result = client.get_kline("BK0438", category="day", start=0, count=5)
        print(f"--- 4.2 eltdx get_kline('BK0438', day): ---")
        print(f"  type: {type(result).__name__}, len: {len(result) if hasattr(result, '__len__') else '?'}")
        for r in result[:3] if hasattr(result, '__getitem__') else []:
            print(f"  {r}")
except Exception as exc:
    print(f"--- 4.2 eltdx get_kline('BK0438', day) 失败: {type(exc).__name__}: {str(exc)[:200]} ---")

# 4.3 板块行情 (用 get_quote 试)
try:
    with eltdx.TdxClient() as client:
        result = client.get_quote("BK0438")
        print(f"--- 4.3 eltdx get_quote('BK0438'): ---")
        print(f"  type: {type(result).__name__}")
        if isinstance(result, list):
            for r in result[:2]:
                print(f"  {r}")
        else:
            print(f"  {result}")
except Exception as exc:
    print(f"--- 4.3 eltdx get_quote('BK0438') 失败: {type(exc).__name__}: {str(exc)[:200]} ---")

# 4.4 limits 涨跌停 (板块有这玩意吗?)
try:
    with eltdx.TdxClient() as client:
        result = client.limits("BK0438")
        print(f"--- 4.4 eltdx limits('BK0438'): ---")
        print(f"  type: {type(result).__name__}, value: {str(result)[:200]}")
except Exception as exc:
    print(f"--- 4.4 eltdx limits('BK0438') 失败: {type(exc).__name__}: {str(exc)[:200]} ---")

print()
print("=" * 70)
print("=== 跑完 ===")
print("=" * 70)
