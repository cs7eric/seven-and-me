"""同花顺 q.10jqka.com.cn 行业成分股 (hexin-v 破解) 业务服务.

数据源:
  - 总索引: ``reference/ths-industry/constituents_index.json``
    一份总索引, 包含 90 行业的成分股代码列表 (membership, 哪个股票属哪个行业)
  - 全量行情: ``reference/stock-universe/ths_industry/constituents/{code}.json``
    每行业一份, 包含全行业 ~2000 只股票 14 列行情 (name, price, changePct, ...).
    数据全, 但量大, 不直接喂给前端, 只用于按 index 的 50 只 code 查行.

老的数据源 (reference/ths-industry/constituents/{code}.json) 已被覆盖, 不再读.

公开接口:
  - ``get_industry_constituents(code, refresh=False)``            -> dict  (走网络, 保留)
  - ``refresh_industry_constituents(code)``                        -> dict  (强制重爬, 保留)
  - ``read_industry_constituents_from_index(code)``                -> dict|None
        只返 code 列表 (membership 视图, 适合只显示代码的轻量场景)
  - ``read_industry_constituents_joined(code)``                    -> dict|None  ★ 推荐
        把 index 的 50 只 code 跟 stock-universe per-industry 的 14 列行情 join,
        返给前端 drawer 渲染 14 列完整行情
  - ``list_cached_codes()``                                       -> list[str]
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from backend.config.settings import (
    THS_INDUSTRY_CONSTITUENTS_DIR,
    THS_INDUSTRY_CONSTITUENTS_INDEX_FILE,
)
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


def read_industry_constituents_from_index(code: str) -> dict[str, Any] | None:
    """直接读 ``reference/ths-industry/constituents_index.json`` 总索引, 按 code 取该行业成分股.

    跟 ``read_industry_constituents_from_disk`` (老接口) 的区别:
      - 数据源从 per-industry 的 90 个文件 换成 1 个总索引文件
      - 一次磁盘 I/O 拿全表, 进程内 LRU 缓存避免反复读盘
      - 不爬网络, 索引文件没有就返 None

    返回:
      {
        "ok": True,
        "code": "881101",
        "stocks": ["920403", "920964", ...],   # 该行业成分股代码列表
        "count": 30,
        "fetchedAt": "2026-06-09T00:51:47",    # 索引文件自身的抓取时间
        "source": "...",
      }
      或 None (索引文件不存在 / 解析失败 / code 不在 byCode 里)
    """
    code = str(code or "").strip()
    if not code:
        return None
    index = _read_index()
    if not index:
        return None
    by_code = index.get("byCode") or {}
    if not isinstance(by_code, dict):
        return None
    stocks = by_code.get(code)
    if not isinstance(stocks, list):
        return None
    return {
        "ok": True,
        "code": code,
        "stocks": [str(s) for s in stocks],
        "count": len(stocks),
        "fetchedAt": index.get("fetchedAt"),
        "source": index.get("source"),
    }


# 老接口保留, 但内部转调索引读, 行为对齐 ``read_industry_constituents_from_index``.
# 旧 ``get_industry_constituents`` 仍走网络 + 落盘, 不受影响.
def read_industry_constituents_from_disk(code: str) -> dict[str, Any] | None:
    """兼容老调用: 走 ``read_industry_constituents_from_index``."""
    return read_industry_constituents_from_index(code)


# ---------------------------------------------------------------------------
# 行业成分股全量视图 (per-industry 文件 14 列, 不再 join index)
# ---------------------------------------------------------------------------
# 数据源: reference/ths-industry/constituents/{code}.json
#   - fetcher 翻全页爬完落盘的, 90 行业全覆盖, pages / rowCount 一致
#   - 14 列字段名: 序号/代码/名称/现价/涨跌幅(%)/涨跌/涨速(%)/换手(%)/量比/振幅(%)/成交额/流通股/流通市值/市盈率
#
# constituents_index.json 弃用 join (独立维护的 50 只 code 跟 per-industry 不一致, join 会有空行)
_SU_LOCK = threading.Lock()
_SU_CACHE: dict[str, tuple[int, dict[str, Any]]] = {}  # code -> (mtime_ns, {rows, fetchedAt})


def read_industry_constituents_joined(code: str) -> dict[str, Any] | None:
    """直接读 ths-industry per-industry 文件, 返该行业全量成分股 14 列行情.

    数据源: ``reference/ths-industry/constituents/{code}.json``
      - fetcher 翻全页爬完落盘的, 90 行业全覆盖
      - 14 列字段名: 序号/代码/名称/现价/涨跌幅(%)/涨跌/涨速(%)/换手(%)/量比/振幅(%)/成交额/流通股/流通市值/市盈率
      - 不同行业行数不一样: 19~100 (受 q.10jqka 翻页上限 5 页 = 100 行 影响)

    注意: 这个不走 constituents_index. index 是另一份独立维护的 code 列表 (50 只), 跟
    per-industry 文件更新时间不一致, join 出来会有空缺, 反而误导用户. 这里直接以
    per-industry 文件为单一来源, 渲染所有行.

    返回:
      {
        "ok": True,
        "code": "881103",
        "name": "种植业与林业",
        "count": 42,                # per-industry 文件实际行数
        "matched": 42,              # 全命中 (per-industry 是单一来源, 不会有 null)
        "rowsFetchedAt": "2026-06-08T19:43:02",
        "rows": [                   # 14 列行情, 文件原顺序
          {
            "序号": 1, "代码": "3030", "名称": "祖名股份", "现价": 23.42,
            "涨跌幅(%)": 10.01, "涨跌": 2.13, "涨速(%)": 0.0,
            "换手(%)": 5.29, "量比": 0.67, "振幅(%)": 10.94,
            "成交额": "0.97亿", "流通股": "0.81亿", "流通市值": "18.96亿", "市盈率": "--"
          },
          ...
        ]
      }
      或 None (per-industry 文件没拿到)
    """
    from backend.services.stock.f10.ths_industry_service import code_to_name

    code = str(code or "").strip()
    if not code:
        return None

    path = THS_INDUSTRY_CONSTITUENTS_DIR / f"{code}.json"
    with _SU_LOCK:
        try:
            current_mtime_ns = path.stat().st_mtime_ns
        except FileNotFoundError:
            return None
        except Exception as exc:
            logger.warning("stat %s failed: %s", path, exc)
            return None
        cached = _SU_CACHE.get(code)
        if cached and cached[0] == current_mtime_ns:
            data, rows_fetched_at = cached[1], cached[1].get("fetchedAt")
            raw_rows = cached[1].get("rows") or []
        else:
            try:
                data_obj = read_json_file(path, default=None)
            except Exception as exc:
                logger.warning("read %s failed: %s", path, exc)
                return None
            if not isinstance(data_obj, dict):
                return None
            raw_rows = data_obj.get("rows") or []
            rows_fetched_at = data_obj.get("fetchedAt")
            # 缓存的是 (data_obj, raw_rows, fetchedAt) 不可变 view, 下面不再写回
            _SU_CACHE[code] = (
                current_mtime_ns,
                {
                    "rows": raw_rows,
                    "fetchedAt": rows_fetched_at,
                },
            )

    rows: list[dict[str, Any]] = []
    for src_row in raw_rows:
        if not isinstance(src_row, dict):
            continue
        rows.append({
            "序号": src_row.get("序号"),
            "代码": str(src_row.get("代码")) if src_row.get("代码") is not None else None,
            "名称": src_row.get("名称"),
            "现价": src_row.get("现价"),
            "涨跌幅(%)": src_row.get("涨跌幅(%)"),
            "涨跌": src_row.get("涨跌"),
            "涨速(%)": src_row.get("涨速(%)"),
            "换手(%)": src_row.get("换手(%)"),
            "量比": src_row.get("量比"),
            "振幅(%)": src_row.get("振幅(%)"),
            "成交额": src_row.get("成交额"),
            "流通股": src_row.get("流通股"),
            "流通市值": src_row.get("流通市值"),
            "市盈率": src_row.get("市盈率"),
        })

    return {
        "ok": True,
        "code": code,
        "name": code_to_name(code) or code,
        "count": len(rows),
        "matched": len(rows),
        "rowsFetchedAt": rows_fetched_at,
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# 索引文件缓存
# 50KB 左右, 一次读完常驻进程; 索引更新由 scheduler 全量重写, 不会增量改,
# 所以 mtime 变了就重读即可. 旧 entry 自然被 GC 掉.
# ---------------------------------------------------------------------------
_index_lock = threading.Lock()
_index_cache: dict[str, Any] | None = None
_index_mtime_ns: int | None = None
_INDEX_PATH: Final[Path] = THS_INDUSTRY_CONSTITUENTS_INDEX_FILE


def _read_index() -> dict[str, Any] | None:
    global _index_cache, _index_mtime_ns
    with _index_lock:
        try:
            current_mtime_ns = _INDEX_PATH.stat().st_mtime_ns
        except FileNotFoundError:
            return None
        except Exception as exc:
            logger.warning("stat %s failed: %s", _INDEX_PATH, exc)
            return None
        if _index_cache is not None and _index_mtime_ns == current_mtime_ns:
            return _index_cache
        try:
            data = read_json_file(_INDEX_PATH, default=None)
        except Exception as exc:
            logger.warning("read %s failed: %s", _INDEX_PATH, exc)
            return None
        if not isinstance(data, dict):
            return None
        _index_cache = data
        _index_mtime_ns = current_mtime_ns
        return data


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
