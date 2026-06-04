"""涨停 / 跌停数量业务层。

把 :mod:`service` 拿到的统计结果落盘到 ``reference/stock/cache/breadth/``，
供 :mod:`market_overview_service` 在 eltdx 数据源优先级下消费。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from backend.config.settings import STOCK_REFERENCE_CACHE_FOLDER
from backend.utils.json_io import read_json_file, write_json_file

from .service import get_fundamentals_service


BREADTH_DIR = STOCK_REFERENCE_CACHE_FOLDER / 'breadth'
BREADTH_LATEST_FILE = BREADTH_DIR / 'eltdx_latest.json'


def _ensure_breadth_dir() -> None:
    BREADTH_DIR.mkdir(parents=True, exist_ok=True)


def refresh_limit_up_down(*, category: str = "沪深A股", max_pages: int = 80) -> dict:
    """强制从 eltdx 拉一次并写盘。"""
    service = get_fundamentals_service()
    payload = service.count_limit_up_down(category=category, max_pages=max_pages)
    payload['refreshed_at'] = datetime.now().isoformat()
    payload['source'] = service.source_name
    _ensure_breadth_dir()
    write_json_file(BREADTH_LATEST_FILE, payload)
    return payload


def read_limit_up_down_cache() -> dict | None:
    """读取最近一次 eltdx 统计结果（不存在返回 None）。"""
    return read_json_file(BREADTH_LATEST_FILE, None)


def merge_into_breadth(breadth_payload: dict) -> dict:
    """把 eltdx 统计合并进 market-breadth 响应，优先使用 eltdx 数据。"""
    cached = read_limit_up_down_cache()
    if not cached:
        return breadth_payload
    for key in (
        'upCount',
        'downCount',
        'limitUpCount',
        'limitDownCount',
        'totalCount',
    ):
        value = cached.get(key)
        if value is None:
            continue
        breadth_payload[key] = value
    breadth_payload['limit_count_source'] = cached.get('source') or 'eltdx'
    return breadth_payload
