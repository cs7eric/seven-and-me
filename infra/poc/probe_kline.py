"""POC v5: 单点验证 push2/push2his K 线 (BK0438, 000300, 000001)."""
import os
import requests

UA = "Mozilla/5.0"
H = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
    os.environ.pop(k, None)
s = requests.Session()
s.trust_env = False

cases = [
    ("1.BK0438", "BK0438"),
    ("1.000300", "HS300"),
    ("1.000001", "SSE"),
    ("0.399001", "SZSE-COMP"),
]
hosts = [
    "http://push2.eastmoney.com",
    "http://push2his.eastmoney.com",
]
for secid, label in cases:
    for host in hosts:
        try:
            r = s.get(
                host + "/api/qt/stock/kline/get",
                params={
                    "secid": secid, "klt": "101", "fqt": "1", "lmt": "3",
                    "fields1": "f1,f2,f3,f4,f5,f6",
                    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                    "beg": "0", "end": "20500101",
                },
                headers=H,
                timeout=(3, 8),
                proxies={"http": None, "https": None},
            )
            j = r.json()
            data = j.get("data") or {}
            klines = data.get("klines") or []
            name = data.get("name") or ""
            print(f"{host:35s} {secid:10s} {label:8s} rc={j.get('rc'):4d} name={name} klines={len(klines)}")
            for k in klines[:2]:
                print(f"    {k[:140]}")
        except Exception as e:
            print(f"{host:35s} {secid:10s} {label:8s} ERR: {type(e).__name__}: {str(e)[:60]}")
    print()
