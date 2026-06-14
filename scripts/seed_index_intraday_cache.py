"""一次性脚本: 批量为三大指数 (000001/399001/399006) 拉最近 N 个交易日的 1m K,
落到 reference/stock/cache/intraday/. 这样前端的 Market Pulse 历史图 click → K 线
首次命中后, 后续所有历史日都是 instant cache hit (不用每次都走 eltdx TCP).

走 /api/index-kline/batch 后端 HTTP 接口, 不直接 import eltdx (避免污染主进程),
跟前端真实调用一致, 走完整 fallback 链 + write_json_file 落盘.

用法: python scripts/seed_index_intraday_cache.py
"""
from __future__ import annotations
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# 跟 backend/runner.py:run_dev_server 默认端口保持一致
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 5000

INDEX_CODES = ["000001", "399001", "399006"]
ARCHIVE_DIR = REPO / "reference" / "market-overview" / "archive"


def _all_trade_dates() -> list[str]:
    if not ARCHIVE_DIR.exists():
        raise SystemExit(f"archive 目录不存在: {ARCHIVE_DIR}")
    files = sorted(ARCHIVE_DIR.glob("*.json"), key=lambda p: p.name, reverse=True)
    return [f.stem for f in files]


def _http_get_json(path: str, params: dict, timeout: int = 60) -> dict:
    from urllib.parse import urlencode
    url = f"http://{BACKEND_HOST}:{BACKEND_PORT}{path}?{urlencode(params)}"
    req = urlrequest.Request(url, headers={"User-Agent": "seed_index_intraday/1.0"})
    req = urlrequest.Request(url, headers={"User-Agent": "seed_index_intraday/1.0"})
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body)


def main() -> int:
    trade_dates = _all_trade_dates()
    if not trade_dates:
        raise SystemExit("archive 目录没有日期文件")
    print(f"将拉取 {len(trade_dates)} 个交易日 × {len(INDEX_CODES)} 个指数 = {len(trade_dates)*len(INDEX_CODES)} 个组合\n")

    ok = 0
    fail = 0
    cache_hit = 0
    t0 = time.time()
    for yyyymmdd in trade_dates:
        yyyy, mm, dd = yyyymmdd[:4], yyyymmdd[4:6], yyyymmdd[6:8]
        iso_date = f"{yyyy}-{mm}-{dd}"
        for code in INDEX_CODES:
            try:
                payload = _http_get_json(
                    "/api/index-kline/batch",
                    {"codes": code, "date": iso_date, "interval": "1m"},
                )
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as e:
                print(f"  FAIL {iso_date} {code}: {e}")
                fail += 1
                continue
            items = payload.get("items") or []
            item = items[0] if items else {}
            if not item.get("ok") or not item.get("points"):
                print(f"  EMPTY {iso_date} {code}: {item.get('error', 'no points')}")
                fail += 1
                continue
            source = item.get("source", "?")
            point_count = len(item["points"])
            if source == "cache":
                cache_hit += 1
            else:
                ok += 1
            print(f"  OK  {iso_date} {code} ({item.get('name')})  src={source:<8}  points={point_count:>3}  "
                  f"open={item['points'][0]['open']}  close={item['points'][-1]['close']}")
            # 限速, 别把 eltdx TCP 打挂
            if source != "cache":
                time.sleep(0.4)

    elapsed = time.time() - t0
    print()
    print(f"完成: 新拉 {ok} 个, 命中 cache {cache_hit} 个, 失败 {fail} 个.  耗时 {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
