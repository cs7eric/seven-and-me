"""行业 / 概念 应用面分析 服务。

跟 :mod:`application_analysis_service` 同样流程形态，但 K 线来源是
**eltdx**（``sh8803XX`` / ``sh8804XX`` 板块指数代码），
分析输出是**本地计算的技术指标**（MA20/60/120/250 + 区间位置 + 涨跌幅），
**不调用 LLM**（先做轻量版）。

target / result 持久化在 :mod:`industry_application_store`，
与 ``application-analysis`` 完全独立。
"""
from __future__ import annotations

import logging
from datetime import datetime
from statistics import mean
from typing import Any

from eltdx import TdxClient

from backend.services.stock.f10.index_codes import (
    CONCEPT_INDEX_CODES,
    INDUSTRY_INDEX_CODES,
)
from backend.services.stock.industry_application_store import (
    history_dir,
    list_result_files,
    load_targets,
    read_result,
    result_path,
    save_targets,
    write_result,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# K-line period 标准化（与 f10/helpers 保持一致）
# ---------------------------------------------------------------------------

_PERIOD_ALIASES: dict[str, int | str] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "60m": 60,
    "1h": 60,
    "1d": "day",
    "1w": "week",
    "1M": "month",
}


def _normalize_period(period: str) -> str:
    key = period.strip()
    if key in _PERIOD_ALIASES:
        return str(_PERIOD_ALIASES[key])
    if key in {"day", "week", "month", "5m", "15m", "30m", "60m", "1m", "year"}:
        return key
    raise ValueError(
        f"不支持的 period: {period!r}，可选 {sorted(_PERIOD_ALIASES.keys())}"
    )


# ---------------------------------------------------------------------------
# 名称解析
# ---------------------------------------------------------------------------


def _lookup_name(target_type: str, symbol: str) -> str:
    code_lower = (symbol or "").strip().lower()
    table = INDUSTRY_INDEX_CODES if target_type == "industry" else CONCEPT_INDEX_CODES
    for c, n in table:
        if c.lower() == code_lower:
            return n
    return symbol


# ---------------------------------------------------------------------------
# K 线 + 指标
# ---------------------------------------------------------------------------


def _fetch_kline(symbol: str, *, period: str, count: int) -> list[dict[str, Any]]:
    normalized = _normalize_period(period)
    with TdxClient(timeout=5) as client:
        page = client.bars.get(
            symbol,
            period=normalized,
            count=count,
            kind="index",
        )
    bars = getattr(page, "bars", None) or []
    out: list[dict[str, Any]] = []
    for bar in bars:
        prev_close_milli = getattr(bar, "last_close_price_milli", None)
        prev_close = (prev_close_milli / 1000.0) if prev_close_milli else None
        pct = None
        if prev_close and prev_close != 0:
            pct = (bar.close / prev_close - 1.0) * 100.0
        out.append(
            {
                "time": str(getattr(bar, "time", "")),
                "open": float(getattr(bar, "open", 0.0)),
                "high": float(getattr(bar, "high", 0.0)),
                "low": float(getattr(bar, "low", 0.0)),
                "close": float(getattr(bar, "close", 0.0)),
                "prev_close": prev_close,
                "pct": pct,
                "volume_lots": int(getattr(bar, "volume_lots", 0) or 0),
                "amount": float(getattr(bar, "amount", 0.0) or 0.0),
            }
        )
    return out


def _ma(values: list[float], n: int) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(values)):
        if i + 1 < n:
            out.append(None)
            continue
        window = values[i + 1 - n : i + 1]
        out.append(mean(window) if window else None)
    return out


def _compute_indicators(bars: list[dict[str, Any]]) -> dict[str, Any]:
    if not bars:
        return {}
    closes = [b["close"] for b in bars]
    ma20 = _ma(closes, 20)
    ma60 = _ma(closes, 60)
    ma120 = _ma(closes, 120)
    ma250 = _ma(closes, 250)
    latest = bars[-1]
    ma20_last = ma20[-1]
    ma60_last = ma60[-1]
    above_ma20 = ma20_last is not None and latest["close"] > ma20_last
    above_ma60 = ma60_last is not None and latest["close"] > ma60_last
    above_ma20_pct = (
        (latest["close"] / ma20_last - 1) * 100 if ma20_last else None
    )
    above_ma60_pct = (
        (latest["close"] / ma60_last - 1) * 100 if ma60_last else None
    )

    high_20 = max(b["high"] for b in bars[-20:]) if len(bars) >= 20 else None
    low_20 = min(b["low"] for b in bars[-20:]) if len(bars) >= 20 else None
    range_pos_20 = None
    if high_20 is not None and low_20 is not None and high_20 != low_20:
        range_pos_20 = (latest["close"] - low_20) / (high_20 - low_20)

    # 区间内连续天数
    above_ma20_streak = 0
    for i in range(len(bars) - 1, -1, -1):
        m = ma20[i]
        if m is None or bars[i]["close"] < m:
            break
        above_ma20_streak += 1

    # 5/20/60 日累计收益
    def period_return(n: int) -> float | None:
        if len(bars) < n + 1:
            return None
        prev = bars[-1 - n]["close"]
        cur = bars[-1]["close"]
        if prev == 0:
            return None
        return (cur / prev - 1) * 100

    return {
        "latest_close": latest["close"],
        "latest_pct": latest.get("pct"),
        "latest_time": latest.get("time"),
        "ma20": ma20_last,
        "ma60": ma60_last,
        "ma120": ma120[-1] if ma120 else None,
        "ma250": ma250[-1] if ma250 else None,
        "above_ma20": above_ma20,
        "above_ma60": above_ma60,
        "above_ma20_pct": above_ma20_pct,
        "above_ma60_pct": above_ma60_pct,
        "above_ma20_streak": above_ma20_streak,
        "high_20": high_20,
        "low_20": low_20,
        "range_pos_20": range_pos_20,
        "return_5d": period_return(5),
        "return_20d": period_return(20),
        "return_60d": period_return(60),
        "bar_count": len(bars),
    }


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def fetch_targets() -> dict[str, Any]:
    return load_targets()


def upsert_targets(payload: dict[str, Any]) -> dict[str, Any]:
    return save_targets(payload)


def fetch_kline(
    target_type: str,
    symbol: str,
    *,
    period: str = "day",
    count: int = 120,
) -> dict[str, Any]:
    """拉 eltdx K 线 + 算技术指标，返回带 ``meta.code/name`` 的 dict。"""
    if target_type not in {"industry", "concept"}:
        raise ValueError(f"target_type 仅支持 industry/concept，收到 {target_type!r}")
    if count <= 0 or count > 2000:
        raise ValueError("count 必须在 1-2000 之间")
    name = _lookup_name(target_type, symbol)
    bars = _fetch_kline(symbol, period=period, count=count)
    indicators = _compute_indicators(bars)
    return {
        "target_type": target_type,
        "code": symbol,
        "name": name,
        "period": _normalize_period(period),
        "kline": bars,
        "indicators": indicators,
        "fetched_at": datetime.now().isoformat(),
        "source": "eltdx",
    }


def refresh_target(item: dict[str, Any], *, period: str = "day", count: int = 120) -> dict[str, Any]:
    """拉一次 K 线 + 写 result.json。"""
    target_type = str(item.get("target_type") or "industry").strip().lower()
    symbol = str(item.get("symbol") or "").strip().lower()
    if not symbol:
        raise ValueError("target.symbol 缺失")
    payload = fetch_kline(target_type, symbol, period=period, count=count)
    paths = write_result(item, payload)
    return {
        "ok": True,
        "target": {
            "id": item.get("id"),
            "target_type": target_type,
            "symbol": symbol,
            "name": item.get("name") or payload["name"],
        },
        "kline_count": len(payload["kline"]),
        "indicators": payload["indicators"],
        "paths": paths,
    }


def fetch_result(target_id: str) -> dict[str, Any] | None:
    """从 targets.json 找到 target_id 对应的 item，然后读 result.json。"""
    targets = load_targets()
    item = next(
        (it for it in targets.get("items", []) if str(it.get("id") or "") == target_id),
        None,
    )
    if item is None:
        return None
    return read_result(item)


def list_all_results() -> list[dict[str, Any]]:
    return list_result_files()


# ---------------------------------------------------------------------------
# 兼容旧 application-analysis 风格的入口（共用一份组件时用到）
# ---------------------------------------------------------------------------


def collect_all_target_codes() -> list[dict[str, str]]:
    """给前端下拉选的全量行业 + 概念代码。"""
    out: list[dict[str, str]] = []
    for c, n in INDUSTRY_INDEX_CODES:
        out.append({"code": c, "name": n, "kind": "industry"})
    for c, n in CONCEPT_INDEX_CODES:
        out.append({"code": c, "name": n, "kind": "concept"})
    return out
