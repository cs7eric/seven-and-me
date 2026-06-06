"""POC v3: 探 Eastmoney 多子域名 + 行业 K 线 + 板块涨跌 + eltdx 能力."""
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

# Eastmoney push2 全子域名 (AKShare 会挨个试)
PUSH2_HOSTS = [
    "http://push2.eastmoney.com",
    "http://push2his.eastmoney.com",
    "http://17.push2.eastmoney.com",
    "http://29.push2.eastmoney.com",
    "http://79.push2.eastmoney.com",
    "http://82.push2.eastmoney.com",
    "https://hsmarketwg.eastmoney.com",
    "https://emweb.securities.eastmoney.com",
    "https://datacenter-web.eastmoney.com",
]


def fetch(url: str, params: dict[str, Any] | None = None, timeout: int = 5) -> dict[str, Any] | None:
    """绕代理 + 短超时扫子域名."""
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
            timeout=(3, timeout),
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


def probe_among_hosts(label: str, path: str, params: dict[str, Any] | None = None) -> tuple[str | None, Any]:
    """逐个 host 试，返回第一个能拿到的 (host, data)."""
    for host in PUSH2_HOSTS:
        url = host + path
        d = fetch(url, params=params)
        if d is not None and d != {}:
            return (host, d)
    return (None, None)


def show(label: str, host: str | None, data: Any) -> None:
    print(f"\n=== {label} ===")
    if host is None:
        print("  [X] 所有子域名都不可达")
        return
    print(f"  [OK] host: {host}")
    if isinstance(data, dict):
        # 打印关键摘要
        if "data" in data and isinstance(data["data"], dict):
            total = data["data"].get("total")
            diff = data["data"].get("diff") or []
            print(f"  total: {total}, diff 前 3 条:")
            for row in diff[:3]:
                print(f"    - {json.dumps(row, ensure_ascii=False)[:160]}")
        elif "data" in data and isinstance(data["data"], list):
            print(f"  data 前 3 条:")
            for row in data["data"][:3]:
                print(f"    - {json.dumps(row, ensure_ascii=False)[:160]}")
        else:
            keys = list(data.keys())[:6]
            print(f"  keys: {keys}")
            for k in keys:
                v = data[k]
                if isinstance(v, list):
                    print(f"  {k}: list[{len(v)}], 前 1 条: {json.dumps(v[0], ensure_ascii=False)[:160] if v else '(empty)'}")
                elif isinstance(v, dict):
                    print(f"  {k}: dict keys = {list(v.keys())[:6]}")
                else:
                    print(f"  {k}: {str(v)[:120]}")
    else:
        print(f"  {json.dumps(data, ensure_ascii=False)[:200]}")


# =============================================================================
# A) 板块成分股 (尝试多子域名)
# =============================================================================
print("\n--- A) 板块成分股 (BK0438 食品饮料) ---")
host, data = probe_among_hosts(
    "BK0438 食品饮料 成分股",
    "/api/qt/clist/get",
    {
        "pn": 1, "pz": 5, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "b:BK0438",
        "fields": "f1,f2,f3,f4,f5,f6,f12,f14",
    },
)
show("A.1 BK0438 食品饮料", host, data)

host, data = probe_among_hosts(
    "BK0475 白酒 成分股",
    "/api/qt/clist/get",
    {
        "pn": 1, "pz": 5, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "b:BK0475",
        "fields": "f1,f2,f3,f4,f5,f6,f12,f14",
    },
)
show("A.2 BK0475 白酒", host, data)

# =============================================================================
# B) 全量行业 / 概念列表 (尝试多子域名)
# =============================================================================
print("\n--- B) 全量行业 / 概念列表 ---")
host, data = probe_among_hosts(
    "申万一级 m:90+t:1",
    "/api/qt/clist/get",
    {
        "pn": 1, "pz": 5, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "m:90+t:1",
        "fields": "f1,f2,f3,f4,f12,f14",
    },
)
show("B.1 申万一级行业", host, data)

host, data = probe_among_hosts(
    "概念 m:90+t:4",
    "/api/qt/clist/get",
    {
        "pn": 1, "pz": 5, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "m:90+t:4",
        "fields": "f1,f2,f3,f4,f12,f14",
    },
)
show("B.2 概念板块", host, data)

# =============================================================================
# C) 行业 / 板块 K 线
# =============================================================================
print("\n--- C) 板块 K 线 ---")
# 板块 secid 规则: 1.BKxxxx (沪深 BK) / 0.BKxxxx (深 BK)
# 路径 C.1: kline/get
host, data = probe_among_hosts(
    "BK0438 日 K 线 (secid=1.BK0438)",
    "/api/qt/stock/kline/get",
    {
        "secid": "1.BK0438",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",  # 101=日 K
        "fqt": "1",
        "beg": "20240101",
        "end": "20260606",
        "lmt": "5",
    },
)
show("C.1 BK0438 日 K 线", host, data)

# 路径 C.2: trends2/get (类似分时但有历史)
host, data = probe_among_hosts(
    "BK0438 trends2 (分时K线)",
    "/api/qt/stock/trends2/get",
    {
        "secid": "1.BK0438",
        "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "iscr": "0",
        "ndays": "5",
    },
)
show("C.2 BK0438 trends2 (近 5 日分时)", host, data)

# 路径 C.3: 行业指数通用 K 线 (HS300 板块指数 1.000300)
host, data = probe_among_hosts(
    "000300 沪深300 日 K 线 (板块指数示例)",
    "/api/qt/stock/kline/get",
    {
        "secid": "1.000300",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "1",
        "beg": "20240101",
        "end": "20260606",
        "lmt": "3",
    },
)
show("C.3 000300 沪深300 日 K 线", host, data)

# =============================================================================
# D) 板块涨跌 (实时快照, 含 f104/f105/f128 涨速等)
# =============================================================================
print("\n--- D) 板块涨跌 (实时) ---")
host, data = probe_among_hosts(
    "BK0438 实时行情 (含涨跌幅)",
    "/api/qt/clist/get",
    {
        "pn": 1, "pz": 5, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "b:BK0438",
        "fields": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f104,f105,f128,f136",
    },
)
show("D.1 BK0438 实时涨跌", host, data)

host, data = probe_among_hosts(
    "申万二级行业 实时涨跌幅排行",
    "/api/qt/clist/get",
    {
        "pn": 1, "pz": 5, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "m:90+t:2",
        "fields": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f104,f105,f128",
    },
)
show("D.2 申万二级行业 涨跌", host, data)

# =============================================================================
# E) eltdx 能力探测 (板块 / 行业 K 线 / 涨跌)
# =============================================================================
print("\n--- E) eltdx 能力 ---")
try:
    import eltdx
    print(f"  eltdx version: {getattr(eltdx, '__version__', '?')}")
    client_methods = [m for m in dir(eltdx.TdxClient) if not m.startswith("_")]
    print(f"  TdxClient 方法 ({len(client_methods)}):")
    for m in client_methods:
        print(f"    - {m}")
except ImportError:
    print("  eltdx 未装，先装:")
    print("    pip install eltdx")

print("\n=== 跑完 ===")
