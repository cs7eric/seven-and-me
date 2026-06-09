"""akshare 同花顺 90 行业 + 成分股爬虫 (HTML parse + Playwright 翻页).

数据源:
  - 行业列表:        ``ak.stock_board_industry_name_ths()``            90 行 {name, code(881xxx)}
  - 行业指数 K 线:    ``ak.stock_board_industry_index_ths(name)``        日 K 975 bars
  - 行业指数 9 项:    ``ak.stock_board_industry_info_ths(name)``         10 项 (今开/昨收/...)
  - 行业成分股列表:  迁移到独立模块 ``ths_industry_constituents_service`` (hexin-v 破解)
                     API 入口: /api/stock-chart/ths-industry/constituents-by-code

接口设计:
  - ``name`` 或 ``code (881xxx)`` 互通
  - 90 行业全量并发爬, 默认 4 路 (Playwright 单浏览器 1 个 page 串行翻页, 1 路就够)
  - 单行业结果本地缓存到 ``reference/stock-universe/ths_industry/constituents/{code}.json``
  - 单行业接口走磁盘缓存
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from backend.config.settings import STOCK_UNIVERSE_DIR

try:
    import akshare as ak  # noqa: F401
    _AKSHARE_AVAILABLE = True
except ImportError:
    _AKSHARE_AVAILABLE = False
    ak = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# 持久化目录
INDUSTRY_DIR: Final[Path] = STOCK_UNIVERSE_DIR / "ths_industry"
INDUSTRY_DIR.mkdir(parents=True, exist_ok=True)
INDUSTRY_LIST_FILE: Final[Path] = INDUSTRY_DIR / "industry_list.json"
INDUSTRY_INFO_FILE: Final[Path] = INDUSTRY_DIR / "industry_info.json"
CONSTITUENTS_DIR: Final[Path] = INDUSTRY_DIR / "constituents"
CONSTITUENTS_DIR.mkdir(parents=True, exist_ok=True)
KLINE_DIR: Final[Path] = INDUSTRY_DIR / "kline"
KLINE_DIR.mkdir(parents=True, exist_ok=True)

# 进程级缓存
_cache_lock = threading.Lock()
_industry_list_cache: dict[str, dict[str, str]] | None = None
_industry_info_cache: dict[str, dict[str, Any]] | None = None


# =============================================================================
# 1. 90 行业列表
# =============================================================================
def _fetch_industry_list_from_ak() -> dict[str, dict[str, str]]:
    df = ak.stock_board_industry_name_ths()
    if df is None or df.empty:
        return {}
    out: dict[str, dict[str, str]] = {}
    for _, row in df.iterrows():
        name = str(row.get("name") or "").strip()
        code = str(row.get("code") or "").strip()
        if not name or not code:
            continue
        out[code] = {"name": name, "code": code}
    return out


def get_industry_list(*, refresh: bool = False) -> dict[str, dict[str, str]]:
    """90 行业列表, 进程内缓存 + 磁盘缓存."""
    global _industry_list_cache
    with _cache_lock:
        if not refresh and _industry_list_cache is not None:
            return dict(_industry_list_cache)
        if not refresh and INDUSTRY_LIST_FILE.exists():
            try:
                blob = json.loads(INDUSTRY_LIST_FILE.read_text(encoding="utf-8"))
                _industry_list_cache = blob.get("byCode") or {}
                if _industry_list_cache:
                    return dict(_industry_list_cache)
            except Exception:
                pass
        try:
            _industry_list_cache = _fetch_industry_list_from_ak()
        except Exception as exc:
            logger.warning("ak.stock_board_industry_name_ths failed: %s", exc)
            _industry_list_cache = {}
        # 写盘
        try:
            name_to_code = {v["name"]: c for c, v in _industry_list_cache.items()}
            INDUSTRY_LIST_FILE.write_text(
                json.dumps({
                    "fetchedAt": datetime.now().isoformat(timespec="seconds"),
                    "byCode": _industry_list_cache, "nameToCode": name_to_code,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("write industry list cache failed: %s", exc)
        return dict(_industry_list_cache)


def name_to_code(name: str) -> str | None:
    if not name: return None
    raw = str(name).strip()
    for code, info in get_industry_list().items():
        if info["name"] == raw:
            return code
    return None


def code_to_name(code: str) -> str | None:
    if not code: return None
    return get_industry_list().get(str(code).strip(), {}).get("name")


def resolve_symbol(name_or_code: str) -> str:
    """统一成 name (akshare / 爬虫都需要 name)."""
    if not name_or_code: return ""
    raw = str(name_or_code).strip()
    if not raw: return ""
    if raw.isdigit() and len(raw) == 6:
        n = code_to_name(raw)
        return n or raw
    return raw


# =============================================================================
# 2. 行业指数 9 项实时
# =============================================================================
def _to_float(s: Any) -> float | None:
    if s is None: return None
    try:
        v = float(s); return v if v == v else None
    except (TypeError, ValueError):
        return None


def _fetch_industry_info_all() -> dict[str, dict[str, Any]]:
    """90 行业 9 项实时, 8 并发 + 失败重试 1 次."""
    items = list(get_industry_list().values())
    out: dict[str, dict[str, Any]] = {}

    def _one(info: dict[str, str]) -> tuple[str, dict[str, Any]] | None:
        name = info["name"]
        for attempt in (1, 2):
            try:
                df = ak.stock_board_industry_info_ths(symbol=name)
            except Exception as exc:
                logger.debug("info %s attempt %d failed: %s", name, attempt, exc)
                time.sleep(0.2)
                continue
            if df is None or df.empty:
                return None
            kvs: dict[str, Any] = {}
            for _, row in df.iterrows():
                kvs[str(row.get("项目") or "").strip()] = row.get("值")
            return name, kvs
        return None

    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="ths-info") as pool:
        futures = [pool.submit(_one, info) for info in items]
        for fut, info in zip(futures, items):
            try:
                r = fut.result(timeout=20)
            except Exception as exc:
                logger.debug("info %s timeout: %s", info["name"], exc)
                continue
            if r:
                out[r[0]] = {"code": info["code"], "kvs": r[1], "fetchedAt": datetime.now().isoformat(timespec="seconds")}

    try:
        INDUSTRY_INFO_FILE.write_text(
            json.dumps({"fetchedAt": datetime.now().isoformat(timespec="seconds"), "byName": out},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("write industry info cache failed: %s", exc)
    return out


def get_industry_info(name_or_code: str, *, refresh: bool = False) -> dict[str, Any] | None:
    target_name = resolve_symbol(name_or_code)
    if not target_name: return None
    global _industry_info_cache
    with _cache_lock:
        if not refresh and _industry_info_cache is not None and target_name in _industry_info_cache:
            return _industry_info_cache[target_name]
        if not refresh and INDUSTRY_INFO_FILE.exists():
            try:
                blob = json.loads(INDUSTRY_INFO_FILE.read_text(encoding="utf-8"))
                _industry_info_cache = blob.get("byName") or {}
                if target_name in _industry_info_cache:
                    return _industry_info_cache[target_name]
            except Exception:
                pass
        try:
            _industry_info_cache = _fetch_industry_info_all()
        except Exception as exc:
            logger.warning("ak industry info all failed: %s", exc)
            _industry_info_cache = {}
    return _industry_info_cache.get(target_name)


# =============================================================================
# 3. 行业指数 K 线
# =============================================================================
def _kline_path(code: str, period: str) -> Path:
    return KLINE_DIR / f"{code}_{period}.json"


def get_industry_kline(name_or_code: str, period: str = "day",
                       start_date: str | None = None,
                       end_date: str | None = None,
                       *, refresh: bool = False) -> list[dict[str, Any]]:
    target_name = resolve_symbol(name_or_code)
    if not target_name: return []
    code = name_to_code(target_name) or target_name
    p = _kline_path(code, period)
    if not refresh and p.exists():
        try:
            blob = json.loads(p.read_text(encoding="utf-8"))
            return blob.get("rows") or []
        except Exception:
            pass
    if not start_date:
        start_date = (date.today() - timedelta(days=365 * 5)).strftime("%Y%m%d")
    if not end_date:
        end_date = date.today().strftime("%Y%m%d")
    try:
        df = ak.stock_board_industry_index_ths(symbol=target_name, start_date=start_date, end_date=end_date)
    except Exception as exc:
        logger.warning("ak.stock_board_industry_index_ths(%s) failed: %s", target_name, exc)
        return []
    rows: list[dict[str, Any]] = []
    if df is not None and not df.empty:
        for _, row in df.iterrows():
            d = row.get("日期")
            rows.append({
                "date":   d.isoformat() if hasattr(d, "isoformat") else str(d),
                "open":   row.get("开盘价"),
                "high":   row.get("最高价"),
                "low":    row.get("最低价"),
                "close":  row.get("收盘价"),
                "volume": row.get("成交量"),
                "amount": row.get("成交额"),
            })
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps({
                "name": target_name, "code": code, "period": period,
                "start_date": start_date, "end_date": end_date,
                "fetchedAt": datetime.now().isoformat(timespec="seconds"),
                "rows": rows,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("write kline cache failed: %s", exc)
    return rows


# =============================================================================
# 4. 行业成分股列表 — 迁移到独立模块 ``ths_industry_constituents_service``
#    (hexin-v 破解版, 仿 ths_fund_flow_adapter)
#    老 Playwright/urllib 实现已删除, 数据契约变为 14 列 (pandas 解析):
#      序号/代码/名称/现价/涨跌幅(%)/涨跌/涨速(%)/换手(%)/量比/振幅(%)/
#      成交额/流通股/流通市值/市盈率
#    API 入口: /api/stock-chart/ths-industry/constituents-by-code
# =============================================================================


# =============================================================================
# 顶层: 一次拿三块
# =============================================================================
def build_industry_payload() -> dict[str, Any]:
    listing = get_industry_list()
    items: list[dict[str, Any]] = []
    for code, info in listing.items():
        name = info["name"]
        kv = get_industry_info(name) or {}
        kvs = kv.get("kvs") or {}
        items.append({
            "code":         code,
            "name":         name,
            "lastPrice":    _to_float(kvs.get("最新")),
            "openPrice":    _to_float(kvs.get("今开")),
            "highPrice":    _to_float(kvs.get("最高")),
            "lowPrice":     _to_float(kvs.get("最低")),
            "change":       _to_float(kvs.get("涨跌额")),
            "changePercent":_to_float(kvs.get("涨跌幅")),
            "volume":       _to_float(kvs.get("成交量(万手)")),
            "amount":       _to_float(kvs.get("成交额(亿)")),
            "turnoverRate": _to_float(kvs.get("换手率")),
            "amplitude":    _to_float(kvs.get("振幅")),
        })
    return {
        "ok": True, "kind": "akshare.ths_industry", "label": "行业 (同花顺)",
        "count": len(items), "items": items,
        "fetchedAt": datetime.now().isoformat(timespec="seconds"),
        "source": "akshare.stock_board_industry_*_ths",
    }
