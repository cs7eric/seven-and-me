"""风格板块 (e.g. 昨日涨停, 微盘股, 百元股) 的板块涨跌幅服务.

读 ``reference/stock-universe/sectors/sectors_styles_4.json`` 拿 29 个
风格板块的成分股 codes, 调腾讯 ``qt.gtimg.cn`` 批量快照取每个 code 的
``change_pct``, 最后用 ``infra.style_sector.compute_sector_change_pct``
做等权平均.

行情 API 返回 ``change_pct`` 是百分数 (e.g. 2.5 表示 +2.5%),
本服务统一转换成百分数输出 (与项目里其他板块 API 一致).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from backend.adapters.market.tencent import fetch_tencent_snapshots
from backend.services.stock.stock_universe_service import list_sectors_by_category
from infra.style_sector import compute_sector_change_pct  # noqa: F401  # 保留兼容老 import; 实际不再用 (等权平均替代)

logger = logging.getLogger(__name__)

STYLES_CATEGORY_RAW = 4  # sectors_styles_4.json

# 对外暴露的 29 个风格板块名
STYLE_SECTOR_NAMES: list[str] = [
    "近期新低", "微小盘股", "微盘股", "近期弱势", "昨日较弱",
    "最近情绪指数", "百元股", "近期新高", "大盘股", "低价股",
    "最近异动", "昨日弱势", "自由现金流", "行业龙头", "历史新低",
    "近期强势", "昨高换手", "昨日涨停", "机构吸筹", "最近多板",
    "昨日跌停", "昨日首板", "昨曾跌停", "历史新高", "昨日较强",
    "昨曾涨停", "昨日强势", "昨日连板", "昨日断板",
]

# 进程内行情缓存 (腾讯 qt.gtimg.cn 批量快照, 30s TTL)
_quote_cache: dict[str, dict[str, Any]] = {}
_quote_cache_at: float = 0.0
_QUOTE_TTL = 30.0
_cache_lock = threading.Lock()


def _codes_by_name() -> dict[str, list[str]]:
    """从 sectors_styles_4.json 读 29 个 style 的 codes (仅返回白名单里的)."""
    out: dict[str, list[str]] = {}
    for s in list_sectors_by_category(STYLES_CATEGORY_RAW):
        name = s.get("name")
        if name in STYLE_SECTOR_NAMES:
            out[name] = list(s.get("stock_codes") or [])
    return out


def _fetch_quotes(codes: list[str]) -> dict[str, dict[str, Any]]:
    """实时行情 (腾讯 qt.gtimg.cn 批量快照) + 进程内 30s 缓存. 失败时返回旧缓存或空 dict."""
    global _quote_cache, _quote_cache_at
    with _cache_lock:
        now = time.time()
        if _quote_cache and (now - _quote_cache_at) < _QUOTE_TTL:
            return _quote_cache
        try:
            quotes = fetch_tencent_snapshots(codes) or {}
        except Exception as exc:
            logger.warning("fetch_tencent_snapshots failed: %s", exc)
            return _quote_cache
        if quotes:
            _quote_cache = quotes
            _quote_cache_at = now
        return _quote_cache


def _compute_one(
    name: str, codes: list[str], quotes: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """单个 style 的计算结果 (百分数, **等权平均**: 成分股当日涨跌幅的算术平均).

    公式: R = (stock1_change_pct + stock2_change_pct + ... + stockN_change_pct) / N
    (跟项目内 "昨日涨停板块涨跌幅 = 昨日涨停股票今日涨跌幅的平均值" 口径一致)

    优选直接用 tencent snapshot 自带的 change_pct (field[32]); 缺失时回退
    ``(last - pre_close) / pre_close * 100``.
    """
    pcts: list[float] = []
    for code in codes:
        q = quotes.get(code)
        if not q:
            continue
        try:
            last = float(q.get("last_price") or 0)
            pre_close = float(q.get("pre_close_price") or 0)
        except (TypeError, ValueError):
            continue
        # 优先 snapshot 自带 change_pct, 缺失时现价算
        pct_raw = q.get("change_pct")
        pct: float | None = None
        if pct_raw is not None and pct_raw != "":
            try:
                pct = float(pct_raw)
            except (TypeError, ValueError):
                pct = None
        if pct is None and last > 0 and pre_close > 0:
            pct = (last - pre_close) / pre_close * 100.0
        if pct is None:
            continue
        pcts.append(pct)
    avg = (sum(pcts) / len(pcts)) if pcts else None
    return {
        "name": name,
        "change_pct": round(avg, 4) if avg is not None else None,
        "valid_size": len(pcts),
        "sample_size": len(codes),
    }


def get_style_sector(name: str) -> dict[str, Any] | None:
    """单个 style 板块涨跌幅 (百分数). 不在 29 个里返回 None."""
    if name not in STYLE_SECTOR_NAMES:
        return None
    codes_by_name = _codes_by_name()
    codes = codes_by_name.get(name, [])
    quotes = _fetch_quotes(codes) if codes else {}
    return _compute_one(name, codes, quotes)


def get_all_style_sectors() -> list[dict[str, Any]]:
    """29 个 style 板块涨跌幅 (百分数), 共享一次行情拉取."""
    codes_by_name = _codes_by_name()
    seen: set[str] = set()
    union: list[str] = []
    for codes in codes_by_name.values():
        for c in codes:
            if c and c not in seen:
                seen.add(c)
                union.append(c)
    quotes = _fetch_quotes(union) if union else {}
    return [
        _compute_one(name, codes_by_name.get(name, []), quotes)
        for name in STYLE_SECTOR_NAMES
    ]
