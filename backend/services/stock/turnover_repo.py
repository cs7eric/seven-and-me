"""换手率单独持久化 repo（per-target）。

存放位置：``reference/stock/turnover/{target_type}-{symbol}.json``。

与之前的差别：换手率**不再**回写 K 线主文件（避免污染 K 线数据源），
而是在本目录单独维护一份按 target 维度的"最近换手率"快照，方便调度器批量更新、
查询时直接 ``set`` 进 stock info 响应里。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from backend.config.settings import STOCK_TURNOVER_DIR
from backend.utils.json_io import read_json_file, write_json_file


def _turnover_file(target_type: str, symbol: str) -> Path:
    safe_tt = (target_type or "stock").strip().lower()
    safe_sym = (symbol or "").strip().lower()
    return STOCK_TURNOVER_DIR / f"{safe_tt}-{safe_sym}.json"


def ensure_dir() -> None:
    STOCK_TURNOVER_DIR.mkdir(parents=True, exist_ok=True)


def load_turnover(target_type: str, symbol: str) -> dict[str, Any] | None:
    """读取单只标的的换手率缓存。无文件返回 ``None``。"""
    return read_json_file(_turnover_file(target_type, symbol), None)


def save_turnover(
    target_type: str,
    symbol: str,
    *,
    entries: list[dict[str, Any]],
    circulating_shares: float | None,
    total_shares: float | None,
    period: str = "1d",
    adjust: str = "qfq",
    source: str = "eltdx",
) -> dict[str, Any]:
    """写入换手率缓存。返回写入后的 payload。"""
    ensure_dir()
    payload = {
        "symbol": symbol,
        "target_type": target_type,
        "period": period,
        "adjust": adjust,
        "circulating_shares": circulating_shares,
        "total_shares": total_shares,
        "source": source,
        "entries": entries,
        "updated_at": datetime.now().isoformat(),
    }
    write_json_file(_turnover_file(target_type, symbol), payload)
    return payload


def list_all_targets_with_turnover() -> list[str]:
    """列出当前所有已写入换手率的标的 key。"""
    if not STOCK_TURNOVER_DIR.exists():
        return []
    return sorted(p.stem for p in STOCK_TURNOVER_DIR.glob("*.json"))


def latest_turnover_entry(target_type: str, symbol: str) -> dict[str, Any] | None:
    """取单只标的最新一根的换手率（按 entries 最后一条）。"""
    payload = load_turnover(target_type, symbol)
    if not payload:
        return None
    entries = payload.get("entries") or []
    if not entries:
        return None
    return entries[-1]


def attach_to_stock_info(
    stock_info_payload: dict[str, Any],
    target_type: str,
    symbol: str,
) -> dict[str, Any]:
    """把换手率塞进 stock info 响应里（在 raw 之外加一个 turnover 顶层字段）。"""
    payload = load_turnover(target_type, symbol)
    if not payload:
        stock_info_payload["turnover"] = None
        return stock_info_payload

    entries = payload.get("entries") or []
    latest = entries[-1] if entries else None
    stock_info_payload["turnover"] = {
        "symbol": symbol,
        "target_type": target_type,
        "circulating_shares": payload.get("circulating_shares"),
        "total_shares": payload.get("total_shares"),
        "source": payload.get("source"),
        "updated_at": payload.get("updated_at"),
        "latest": latest,
        "entries": entries,
    }
    return stock_info_payload
