"""手动粘贴的资金流数据 (主力净流入 / 4 单 净流入 + 净比).

数据源: 东方财富资金流页面 (https://data.eastmoney.com/zjlx/) 手动复制粘贴.
落盘: reference/market-overview/fund-flow/manual/YYYYMMDD.json (按交易日归档).

跟 akshare 资金流并存 — 当 manual 数据存在时, 前端优先用 manual 覆盖 overview.
manual 不含 prevDay 数据, diff badge 仍走 overview.prevDayFlow.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.config.settings import MARKET_OVERVIEW_FOLDER

logger = logging.getLogger(__name__)

# reference/market-overview/fund-flow/manual/YYYYMMDD.json
MANUAL_DIR: Path = MARKET_OVERVIEW_FOLDER / "fund-flow" / "manual"
MANUAL_DIR.mkdir(parents=True, exist_ok=True)


def _manual_path(trading_date: str) -> Path:
    """trading_date: YYYY-MM-DD."""
    return MANUAL_DIR / f"{trading_date.replace('-', '')}.json"


def save_manual_fund_flow(trading_date: str, fields: dict[str, Any]) -> dict[str, Any]:
    """保存手动粘贴的资金流数据. 覆盖式写入 (同日多次保存取最后一次).

    Args:
        trading_date: YYYY-MM-DD
        fields: {mainNetInflow, mainNetInflowRatio, superLargeNetInflow, ...}
                不要求全部, 缺失字段保留 None (前端展示 "—")

    Returns:
        落盘后的完整 payload.
    """
    # 只接受这 10 个字段, 防止前端误传脏数据
    allowed = {
        "mainNetInflow", "mainNetInflowRatio",
        "superLargeNetInflow", "superLargeNetInflowRatio",
        "largeNetInflow", "largeNetInflowRatio",
        "mediumNetInflow", "mediumNetInflowRatio",
        "smallNetInflow", "smallNetInflowRatio",
    }
    cleaned: dict[str, Any] = {}
    for k, v in fields.items():
        if k in allowed and v is not None:
            try:
                cleaned[k] = float(v)
            except (TypeError, ValueError):
                continue

    payload: dict[str, Any] = {
        "tradingDate": trading_date,
        "savedAt": datetime.now().isoformat(timespec="seconds"),
        "source": "manual",
        **cleaned,
    }
    # 没传任何字段时, 兜底把缺的字段写 None (避免 latest 出现半残数据)
    for k in allowed:
        payload.setdefault(k, None)

    path = _manual_path(trading_date)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    logger.info("manual fund flow saved: %s (fields=%d)", path.name, len(cleaned))
    return payload


def load_manual_fund_flow(trading_date: str) -> dict[str, Any] | None:
    """读手动粘贴的资金流数据. 不存在 / 解析失败 / 字段全 None 都返 None."""
    path = _manual_path(trading_date)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("read manual fund flow %s failed: %s", path, exc)
        return None
    if not isinstance(data, dict):
        return None
    # 所有字段都是 None → 当作不存在
    has_any_value = any(
        data.get(k) is not None
        for k in (
            "mainNetInflow", "superLargeNetInflow", "largeNetInflow",
            "mediumNetInflow", "smallNetInflow",
        )
    )
    return data if has_any_value else None
