"""POC v2: 用项目里现成的 headers + HTTP（不是 HTTPS）再试 push2。"""
from __future__ import annotations

import json
import os

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://quote.eastmoney.com/",
    "Origin": "https://quote.eastmoney.com",
}


def fetch(url, params=None):
    proxy_keys = ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]
    backup = {k: os.environ.get(k) for k in proxy_keys}
    for k in proxy_keys:
        os.environ.pop(k, None)
    try:
        s = requests.Session()
        s.trust_env = False
        r = s.get(url, params=params, headers=HEADERS, timeout=(5, 15), proxies={"http": None, "https": None})
        r.raise_for_status()
        return r.json()
    finally:
        for k, v in backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


print("=== push2 HTTP (项目同款) ===")
data = fetch("http://push2.eastmoney.com/api/qt/clist/get", {
    "pn": 1, "pz": 5, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f3",
    "fs": "b:BK0438",
    "fields": "f1,f2,f3,f4,f5,f6,f12,f14",
})
if data:
    print("data.total:", data.get("data", {}).get("total"))
    for row in data.get("data", {}).get("diff", [])[:3]:
        print("  -", json.dumps(row, ensure_ascii=False))

print("\n=== 申万二级 m:90+t:2 ===")
data = fetch("http://push2.eastmoney.com/api/qt/clist/get", {
    "pn": 1, "pz": 5, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f3",
    "fs": "m:90+t:2",
    "fields": "f1,f2,f3,f4,f12,f14",
})
if data:
    print("data.total:", data.get("data", {}).get("total"))
    for row in data.get("data", {}).get("diff", [])[:3]:
        print("  -", json.dumps(row, ensure_ascii=False))

print("\n=== 概念 m:90+t:4 ===")
data = fetch("http://push2.eastmoney.com/api/qt/clist/get", {
    "pn": 1, "pz": 5, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f3",
    "fs": "m:90+t:4",
    "fields": "f1,f2,f3,f4,f12,f14",
})
if data:
    print("data.total:", data.get("data", {}).get("total"))
    for row in data.get("data", {}).get("diff", [])[:3]:
        print("  -", json.dumps(row, ensure_ascii=False))

print("\n=== 沪深京 A 股全量 m:0+t:6+m:0+t:13+m:0+t:80+m:1+t:2+m:1+t:23 ===")
data = fetch("http://push2.eastmoney.com/api/qt/clist/get", {
    "pn": 1, "pz": 5, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f3",
    "fs": "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23",
    "fields": "f1,f2,f3,f4,f12,f14",
})
if data:
    print("data.total:", data.get("data", {}).get("total"))
    for row in data.get("data", {}).get("diff", [])[:3]:
        print("  -", json.dumps(row, ensure_ascii=False))
