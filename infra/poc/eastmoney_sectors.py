"""POC: 探测 Eastmoney 关于板块/概念/行业的几个关键 API。

跑这个脚本看哪些能用、字段结构什么样、TTL 大概要设多久。

能力矩阵（这次 POC 目标）：
  1. 某只票所属的板块/概念/行业（按股票 code 反查）
  2. 某板块/概念/行业下的成分股（按 BK code 查）
  3. Eastmoney 所有板块/概念/行业列表（全量）

不引入任何项目依赖，只用 `requests`。命中后回报告 + 退出。
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any
from urllib.parse import urlencode

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://data.eastmoney.com/",
}


def fetch_json(url: str, params: dict[str, Any] | None = None, timeout: int = 15) -> dict[str, Any] | None:
    """跟项目里的 eastmoney adapter 一样：trust_env=False + proxies=None 绕过系统代理。"""
    try:
        proxy_keys = ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]
        backup = {k: os.environ.get(k) for k in proxy_keys}
        for k in proxy_keys:
            os.environ.pop(k, None)
        try:
            session = requests.Session()
            session.trust_env = False
            resp = session.get(
                url,
                params=params,
                headers=HEADERS,
                timeout=(5, timeout),
                proxies={"http": None, "https": None},
            )
            resp.raise_for_status()
            return resp.json()
        finally:
            for k, v in backup.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    except Exception as exc:
        print(f"  ! 请求失败: {exc}")
        return None


def preview(name: str, data: Any, max_items: int = 3) -> None:
    print(f"\n=== {name} ===")
    if data is None:
        print("  (无数据)")
        return
    if isinstance(data, dict):
        for k, v in list(data.items())[:8]:
            if isinstance(v, list):
                preview_inner = v[:max_items]
                print(f"  {k}: list[{len(v)}], 前 {len(preview_inner)} 条:")
                for item in preview_inner:
                    print(f"    - {json.dumps(item, ensure_ascii=False)[:160]}")
            elif isinstance(v, dict):
                print(f"  {k}: {json.dumps(v, ensure_ascii=False)[:160]}")
            else:
                print(f"  {k}: {v}")
    else:
        print(json.dumps(data, ensure_ascii=False)[:500])


# =============================================================================
# 1) 某只票所属的板块 / 概念 / 行业
# =============================================================================
def poc_stock_belongs_to(symbol: str = "600519") -> None:
    """某只票 → 所属的板块 / 概念 / 行业。"""
    print(f"\n>>> [1] 股票 {symbol} 所属板块 / 概念 / 行业")
    # 路径 A: PC_HSF10 / CompanySurvey (个股 F10 资料) — 基础 + 关联
    url1 = "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax"
    data1 = fetch_json(url1, {"code": f"SH{symbol}"})
    preview("emweb PC_HSF10/CompanySurvey/PageAjax (SH prefix)", data1)

    # 路径 B: PC_HSF10 / CoreConception — 核心题材 / 概念
    url2 = "https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/PageAjax"
    data2 = fetch_json(url2, {"code": f"SH{symbol}"})
    preview("emweb PC_HSF10/CoreConception/PageAjax (SH prefix)", data2)

    # 路径 C: PC_HSF10 / NewFinanceAnalysis / IndustryAjax — 行业归属
    url3 = "https://emweb.securities.eastmoney.com/PC_HSF10/IndustryAjax/PageAjax"
    data3 = fetch_json(url3, {"code": f"SH{symbol}"})
    preview("emweb PC_HSF10/IndustryAjax/PageAjax (SH prefix)", data3)

    # 路径 D: PC_HSF10 / StockRelative — 相关板块
    url4 = "https://emweb.securities.eastmoney.com/PC_HSF10/StockRelative/PageAjax"
    data4 = fetch_json(url4, {"code": f"SH{symbol}"})
    preview("emweb PC_HSF10/StockRelative/PageAjax (SH prefix)", data4)


# =============================================================================
# 2) 板块 / 概念 / 行业下的成分股
# =============================================================================


def _sector_clist_query(bk_code: str, page_size: int = 50) -> dict[str, Any] | None:
    """push2 接口是 Eastmoney 行情核心，按 BK code 拉成分股."""
    fields = "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f22,f11,f62,f128,f136,f115,f152"
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1,
        "pz": page_size,
        "po": 1,
        "np": 1,
        "fltt": 2,
        "invt": 2,
        "fid": "f3",
        "fs": f"b:{bk_code}",
        "fields": fields,
    }
    return fetch_json(url, params)


def poc_sector_constituents(bk_code: str = "BK0438") -> None:
    """某 BK code → 成分股."""
    print(f"\n>>> [2] 板块/概念 {bk_code} 的成分股")
    data = _sector_clist_query(bk_code, page_size=10)
    preview(f"push2 clist (BK={bk_code})", data)


# =============================================================================
# 3) Eastmoney 所有板块 / 概念 / 行业列表
# =============================================================================


def poc_list_all_sectors() -> None:
    print("\n>>> [3] Eastmoney 全量板块 / 行业 / 概念列表")
    # 行业: m:90+t:2 (申万二级), m:90+t:1 (申万一级)
    for label, fs in [
        ("申万一级行业", "m:90+t:1"),
        ("申万二级行业", "m:90+t:2"),
        ("申万三级行业", "m:90+t:3"),
        ("概念板块", "m:90+t:4"),
    ]:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": 1,
            "pz": 5,
            "po": 1,
            "np": 1,
            "fltt": 2,
            "invt": 2,
            "fid": "f3",
            "fs": fs,
            "fields": "f1,f2,f3,f4,f12,f14",
        }
        data = fetch_json(url, params)
        preview(f"push2 clist ({label}, fs={fs})", data)


def main() -> int:
    start = time.time()
    poc_stock_belongs_to("600519")  # 贵州茅台
    poc_sector_constituents("BK0438")  # 随便挑一个 BK code
    poc_list_all_sectors()
    print(f"\n=== POC 耗时: {time.time() - start:.1f}s ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
