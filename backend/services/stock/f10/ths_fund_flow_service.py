"""同花顺全行业主力资金 (hexin-v 破解) 业务服务.

落盘约定:
  ``reference/ths-fund-flow/``
    ├─ latest.json           全量最新一份, API 直接读这份 (默认)
    └─ history/<YYYY-MM-DD>.json  每日 15:30 盘后归档

数据来源:
  ``backend/adapters/market/ths_fund_flow_adapter.py`` —— py_mini_racer 跑 ths.js
  生成 hexin-v, 走 ``http://data.10jqka.com.cn/funds/hyzj1/`` 多页爬.

字段口径 (与 adapter 一致):
  rank           序号 (按净额 desc 重新排名)
  industry       行业
  change_pct     行业指数涨跌幅 (%)
  inflow         流入资金 (亿)
  outflow        流出资金 (亿)
  net            净额 (亿)
  company_count  公司家数
  leader_stock   领涨股
  leader_change  领涨股涨跌幅 (%)
  leader_price   当前价 (元)

接口:
  - ``get_industry_fund_flow(refresh=False)`` -> dict  (读磁盘/触发刷新)
  - ``refresh_industry_fund_flow()`` -> dict           (强制爬一遍, 写 latest+history)
  - ``read_latest()`` -> dict | None                   (供定时任务读档)
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from backend.config.settings import THS_FUND_FLOW_DIR
from backend.utils.json_io import read_json_file, write_json_file

logger = logging.getLogger(__name__)

LATEST_FILE: Final[Path] = THS_FUND_FLOW_DIR / "latest.json"
HISTORY_DIR: Final[Path] = THS_FUND_FLOW_DIR / "history"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)

# 进程级缓存 + 写锁 (避免并发触发重复爬)
_lock = threading.Lock()
_cache: dict[str, Any] | None = None
_cache_at: datetime | None = None

# 缓存有效期 (秒) — 盘中 5 分钟, 同花顺 hexin-v 几分钟就过期, 但 5 分钟内重复
# 触发重爬是浪费; 盘后直接重爬
_CACHE_TTL_SECONDS: Final[int] = 5 * 60


def _history_path(trade_date: str | None = None) -> Path:
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y-%m-%d")
    return HISTORY_DIR / f"{trade_date}.json"


def _serialize(payload: dict[str, Any]) -> dict[str, Any]:
    """包装一层 ok=True, 给前端更省事."""
    return {
        "ok": True,
        "rowCount": payload.get("rowCount", len(payload.get("rows") or [])),
        "totalPages": payload.get("totalPages"),
        "pageRowCounts": payload.get("pageRowCounts") or [],
        "fetchedAt": payload.get("fetchedAt"),
        "rows": payload.get("rows") or [],
    }


def read_latest() -> dict[str, Any] | None:
    """读磁盘 latest.json, 不爬网络."""
    if not LATEST_FILE.exists():
        return None
    try:
        return read_json_file(LATEST_FILE)
    except Exception as exc:
        logger.warning("read %s failed: %s", LATEST_FILE, exc)
        return None


def _is_cache_fresh() -> bool:
    if _cache is None or _cache_at is None:
        return False
    return (datetime.now() - _cache_at).total_seconds() < _CACHE_TTL_SECONDS


def get_industry_fund_flow(*, refresh: bool = False) -> dict[str, Any]:
    """拿全行业主力资金; refresh=True 强制重爬, 否则优先用进程内缓存 → 磁盘缓存.

    返回值: ``{ok, rowCount, totalPages, pageRowCounts, fetchedAt, rows, ...}``
    """
    with _lock:
        if not refresh and _is_cache_fresh() and _cache is not None:
            return _cache
        if not refresh:
            disk = read_latest()
            if disk and (disk.get("rows") or []):
                _cache = disk
                _cache_at = datetime.now()
                return _cache
        # 走网络
        try:
            raw = refresh_industry_fund_flow()
        except Exception as exc:
            logger.exception("refresh_industry_fund_flow failed: %s", exc)
            # 失败时退到磁盘 (旧数据, 标记 stale)
            disk = read_latest()
            if disk:
                disk = dict(disk)
                disk["stale"] = True
                disk["staleReason"] = str(exc)
                _cache = disk
                _cache_at = datetime.now()
                return _cache
            # 磁盘也没有 -> 返空 + ok=False
            return {
                "ok": False,
                "rowCount": 0,
                "rows": [],
                "error": str(exc),
                "fetchedAt": datetime.now().isoformat(timespec="seconds"),
            }
        _cache = raw
        _cache_at = datetime.now()
        return _cache


def refresh_industry_fund_flow() -> dict[str, Any]:
    """强制爬一遍, 写 latest + 今日 history, 返回包装好的 dict."""
    from backend.adapters.market.ths_fund_flow_adapter import fetch_industry_fund_flow_all

    raw = fetch_industry_fund_flow_all()
    payload = _serialize(raw)
    # 写盘: atomic write
    try:
        write_json_file(LATEST_FILE, payload)
    except Exception as exc:
        logger.warning("write %s failed: %s", LATEST_FILE, exc)
    # 今日归档
    try:
        history_blob = dict(payload)
        history_blob["archivedAt"] = datetime.now().isoformat(timespec="seconds")
        write_json_file(_history_path(), history_blob)
    except Exception as exc:
        logger.warning("write history failed: %s", exc)

    # 顺手落 duckdb (写穿: 90 行业 当日快照, 字段级 INSERT OR REPLACE 幂等)
    # 不动 latest.json / history/*.json 现有落盘, 失败不影响主流程
    try:
        from backend.repositories.market.ths_industry_fund_flow_repo import upsert_fund_flow
        upsert_fund_flow(
            payload.get("rows") or [],
            trade_date=datetime.now().strftime("%Y-%m-%d"),
            source="ths.10jqka.com.cn",
        )
    except Exception as exc:
        logger.debug("upsert ths_industry_fund_flow to duckdb failed (non-fatal): %s", exc)

    return payload


def list_history_dates() -> list[str]:
    """列出有归档的日期 (yyyy-mm-dd), 倒序."""
    if not HISTORY_DIR.exists():
        return []
    return sorted(
        (p.stem for p in HISTORY_DIR.glob("*.json")),
        reverse=True,
    )


def read_history(trade_date: str) -> dict[str, Any] | None:
    p = _history_path(trade_date)
    if not p.exists():
        return None
    try:
        return read_json_file(p)
    except Exception as exc:
        logger.warning("read %s failed: %s", p, exc)
        return None
