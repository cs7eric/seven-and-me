"""换手率业务层：把 :mod:`service` 算出的换手率序列**单独**持久化。

⚠️ 行为变更（2026-06-03）
============================
- 之前：写回 ``reference/stock/cache/klines/{target_type}-{symbol}-{period}-{adjust}.json``
  （污染 K 线主文件）。
- 现在：写到 ``reference/stock/turnover/{target_type}-{symbol}.json`` 单独文件，
  通过 :mod:`backend.services.stock.turnover_repo` 维护。

调用方：
- :mod:`backend.services.scheduler.turnover_scheduler`（盘内 30 分钟 + 16:00 收盘后）
- :func:`refresh_turnover_rate` 路由 ``/api/stock-chart/turnover/refresh``
- :func:`refresh_all_targets_turnover` 路由 ``/api/stock-chart/turnover/refresh-all``
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from backend.services.stock.turnover_repo import (
    load_turnover,
    save_turnover,
)

from .eltdx_adapter import EltdxFundamentalsAdapter
from .eltdx_adapter import EltdxFundamentalsAdapter
from .service import get_fundamentals_service


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def refresh_turnover_rate(
    symbol: str,
    target_type: str,
    period: str = "1d",
    adjust: str = "qfq",
) -> dict[str, Any]:
    """计算并写入单只标的的换手率（不再写 K 线主文件）。

    这里显式绕过 service 的 F10 TTL 缓存，避免把历史错误的 turnover cache
    再次写回独立 turnover 文件。
    """
    adapter = EltdxFundamentalsAdapter()
    series_obj = adapter.compute_turnover_rate_series(symbol, target_type, period=period, adjust=adjust)
    series = series_obj.to_dict()
    saved = save_turnover(
        target_type=target_type,
        symbol=symbol,
        entries=series.get("entries", []),
        circulating_shares=series.get("circulating_shares"),
        total_shares=series.get("total_shares"),
        period=period,
        adjust=adjust,
        source=series.get("source", "eltdx"),
    )
    return {
        "symbol": symbol,
        "target_type": target_type,
        "period": period,
        "adjust": adjust,
        "circulating_shares": saved.get("circulating_shares"),
        "total_shares": saved.get("total_shares"),
        "entry_count": len(saved.get("entries", [])),
        "updated_at": saved.get("updated_at"),
        "turnover_source": saved.get("source"),
    }


def refresh_all_targets_turnover(
    targets: Iterable[dict[str, Any]],
    period: str = "1d",
    adjust: str = "qfq",
) -> dict[str, Any]:
    """批量给一组 target 跑换手率刷新。

    ``targets`` 是 :func:`load_application_analysis_targets` 的 items 列表，
    形如 ``{"id": "stock-600021", "target_type": "stock", "symbol": "600021", "enabled": true}``。
    """
    started = datetime.now()
    results: list[dict[str, Any]] = []
    succeeded = 0
    failed = 0
    for target in targets:
        if not target.get("enabled", True):
            continue
        target_id = target.get("id")
        symbol = target.get("symbol")
        target_type = target.get("target_type") or "stock"
        adj = target.get("adjust") or adjust
        try:
            payload = refresh_turnover_rate(
                symbol=symbol,
                target_type=target_type,
                period=period,
                adjust=adj,
            )
            payload["id"] = target_id
            payload["status"] = "success"
            succeeded += 1
        except Exception as exc:
            payload = {
                "id": target_id,
                "symbol": symbol,
                "target_type": target_type,
                "status": "failed",
                "error": str(exc),
            }
            failed += 1
        results.append(payload)
    elapsed = (datetime.now() - started).total_seconds()
    return {
        "succeeded": succeeded,
        "failed": failed,
        "total": succeeded + failed,
        "elapsed_seconds": round(elapsed, 3),
        "started_at": started.isoformat(),
        "results": results,
    }


def read_turnover_snapshot(target_type: str, symbol: str) -> dict[str, Any] | None:
    """读取已经持久化的换手率快照（无数据返回 ``None``）。"""
    return load_turnover(target_type, symbol)
