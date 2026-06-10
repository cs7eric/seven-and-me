"""同花顺 q.10jqka.com.cn 行业成分股 (hexin-v 破解) 业务服务.

落盘约定:
  ``reference/stock-universe/ths_industry/constituents/{code}.json``
  每行业一份, 含 rows + 抓取时间 + 总页数. 复用 ths_industry_service 落盘目录.

公开接口:
  - ``get_industry_constituents(code, refresh=False)`` -> dict
  - ``refresh_industry_constituents(code)``             -> dict (强制重爬)
  - ``list_cached_codes()``                            -> list[str]

返回 (跟 ths_fund_flow 风格保持一致):
  {
    "ok": True,
    "code": "881268",
    "totalPages": 2,
    "pageRowCounts": [20, 16],
    "fetchedAt": "2026-06-08T...",
    "rowCount": 36,
    "rows": [
      {"序号": 1, "代码": 920839, "名称": "万通液压", "现价": 34.1, ...},
      ...
    ]
  }
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from backend.config.settings import THS_INDUSTRY_CONSTITUENTS_DIR
from backend.utils.json_io import read_json_file, write_json_file

logger = logging.getLogger(__name__)

# 落盘目录: ``reference/ths-industry/constituents/{code}.json``
# 跟 industry_list.json 同一根目录, 由 ths_industry_constituents_scheduler
# 每周六 18:00 全量重爬. API 默认从磁盘读, 磁盘没有才爬网络.
CONSTITUENTS_DIR: Final[Path] = THS_INDUSTRY_CONSTITUENTS_DIR
CONSTITUENTS_DIR.mkdir(parents=True, exist_ok=True)


def _constituents_path(code: str) -> Path:
    return CONSTITUENTS_DIR / f"{code}.json"


def _serialize(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "code": payload.get("code"),
        "totalPages": payload.get("totalPages"),
        "pageRowCounts": payload.get("pageRowCounts") or [],
        "fetchedAt": payload.get("fetchedAt"),
        "rowCount": payload.get("rowCount", len(payload.get("rows") or [])),
        "rows": payload.get("rows") or [],
    }


# 进程级缓存 (避免同一进程重复爬同一行业)
_cache_lock = threading.Lock()
_cache: dict[str, dict[str, Any]] = {}


def get_industry_constituents(code: str, *, refresh: bool = False) -> dict[str, Any]:
    """拿单行业成分股. refresh=True 强制重爬; 否则优先进程缓存 -> 磁盘缓存 -> 爬."""
    code = str(code or "").strip()
    if not code:
        return {
            "ok": False,
            "error": "code is required",
            "rows": [],
            "rowCount": 0,
        }
    with _cache_lock:
        if not refresh and code in _cache:
            return _cache[code]
        if not refresh:
            disk = _read_disk(code)
            if disk and (disk.get("rows") or []):
                _cache[code] = disk
                return disk
        try:
            payload = refresh_industry_constituents(code)
        except Exception as exc:
            logger.exception("refresh_industry_constituents %s failed: %s", code, exc)
            # 退到磁盘 (旧数据, 标记 stale)
            disk = _read_disk(code)
            if disk:
                disk = dict(disk)
                disk["stale"] = True
                disk["staleReason"] = str(exc)
                _cache[code] = disk
                return disk
            return {
                "ok": False,
                "code": code,
                "error": str(exc),
                "rows": [],
                "rowCount": 0,
            }
        _cache[code] = payload
        return payload


def refresh_industry_constituents(code: str) -> dict[str, Any]:
    """强制重爬单行业成分股 + 落盘."""
    from backend.adapters.market.ths_industry_constituents_adapter import (
        fetch_industry_constituents_all,
    )
    raw = fetch_industry_constituents_all(code)
    payload = _serialize(raw)
    try:
        write_json_file(_constituents_path(code), payload)
    except Exception as exc:
        logger.warning("write %s failed: %s", _constituents_path(code), exc)
    return payload


def list_cached_codes() -> list[str]:
    if not CONSTITUENTS_DIR.exists():
        return []
    return sorted(p.stem for p in CONSTITUENTS_DIR.glob("*.json"))


def read_industry_constituents_from_disk(code: str) -> dict[str, Any] | None:
    """直接读 ``reference/ths-industry/constituents/{code}.json`` 落盘文件.

    跟 ``get_industry_constituents`` 的区别:
      - 不查进程级内存缓存
      - 不爬网络 (磁盘没有就返 None, 由调用方决定是报 404 还是退回去爬)
      - 一次磁盘 I/O, 适合前端 drawer 「打开默认」高频场景

    返回值就是落盘 JSON 的内容 (ok / code / totalPages / pageRowCounts /
    fetchedAt / rowCount / rows).
    """
    code = str(code or "").strip()
    if not code:
        return None
    return _read_disk(code)


def get_all_industry_constituents(
    *,
    refresh: bool = False,
    inter_industry_sleep: float = 1.5,
    inter_industry_sleep_jitter: float = 0.5,
) -> dict[str, dict[str, Any]]:
    """90 行业全量成分股, 走新 hexin-v 爬虫.

    跟老 Playwright 实现区别:
    - 不再起浏览器, 直接 hexin-v + requests.get
    - 90 行业可以放慢 sleep (q.10jqka 比 data.10jqka 严, 但单行业 hexin-v
      跟总行业 8s 间隔比, 风险在总行业)
    - 默认 1.5s/行业 (老实现 8s), 整轮约 90 * 1.5 = 135s + 单行业 ~5-15s
    - inter_industry_sleep_jitter: sleep 在 [s*(1-j), s*(1+j)] 区间随机
    """
    import random
    from backend.services.stock.f10.ths_industry_service import get_industry_list
    import time

    items = get_industry_list()  # {code: {name, code}}
    out: dict[str, dict[str, Any]] = {}
    for code in items.keys():
        if not refresh:
            disk = _read_disk(code)
            if disk and (disk.get("rows") or []):
                out[code] = disk
                continue
        try:
            payload = refresh_industry_constituents(code)
            if payload.get("rows"):
                out[code] = payload
        except Exception as exc:
            logger.warning("cons-all %s failed: %s", code, exc)
        if inter_industry_sleep > 0:
            jitter = 1.0 + random.uniform(-inter_industry_sleep_jitter, inter_industry_sleep_jitter)
            time.sleep(inter_industry_sleep * jitter)
    return out


def _read_disk(code: str) -> dict[str, Any] | None:
    p = _constituents_path(code)
    if not p.exists():
        return None
    try:
        blob = read_json_file(p, default=None)
        if isinstance(blob, dict):
            return blob
    except Exception as exc:
        logger.warning("read %s failed: %s", p, exc)
    return None
