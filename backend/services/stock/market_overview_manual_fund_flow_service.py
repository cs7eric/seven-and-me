"""手动粘贴的资金流数据 (主力净流入 / 4 单 净流入 + 净比).

数据源: 东方财富资金流页面 (https://data.eastmoney.com/zjlx/) 手动复制粘贴.
落盘:
  1. reference/market-overview/fund-flow/manual/YYYYMMDD.json (manual 源文件, 永久保留)
  2. reference/market-overview/archive/YYYYMMDD.json        (merge 进 archive, 让"市场脉搏"
                                                              资金潮汐/资金结构 趋势图直接读到)

manual 是用户的手动数据 (收盘后补录, akshare 抓不到时), 必须 merge 进 archive 才能让
fund-flow latest / market-pulse history 立刻看到正确数字 (不再依赖 fallback 链).

merge 策略: manual 字段覆盖 archive 同名字段; archive 已有但 manual 没有的字段 (e.g. akshare 写
的 totalAmount / 涨跌家数) 保留不动. source 字段标 "manual+<原source>".
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.config.settings import MARKET_OVERVIEW_FOLDER, MARKET_OVERVIEW_ARCHIVE_DIR

logger = logging.getLogger(__name__)

# reference/market-overview/fund-flow/manual/YYYYMMDD.json
MANUAL_DIR: Path = MARKET_OVERVIEW_FOLDER / "fund-flow" / "manual"
MANUAL_DIR.mkdir(parents=True, exist_ok=True)

# manual 同步 merge 进 archive 的字段 (10 个资金流字段)
_MANUAL_MERGE_FIELDS = (
    "mainNetInflow", "mainNetInflowRatio",
    "superLargeNetInflow", "superLargeNetInflowRatio",
    "largeNetInflow", "largeNetInflowRatio",
    "mediumNetInflow", "mediumNetInflowRatio",
    "smallNetInflow", "smallNetInflowRatio",
)


def _manual_path(trading_date: str) -> Path:
    """trading_date: YYYY-MM-DD."""
    return MANUAL_DIR / f"{trading_date.replace('-', '')}.json"


def _archive_path(trading_date: str) -> Path:
    """reference/market-overview/archive/YYYYMMDD.json (shared with akshare / eltdx)."""
    return MARKET_OVERVIEW_ARCHIVE_DIR / f"{trading_date.replace('-', '')}.json"


def _merge_into_archive(trading_date: str, cleaned: dict[str, Any]) -> None:
    """把 manual 字段 merge 进 archive/<date>.json, 保留其它字段 (akshare 写的 totalAmount / 涨跌家数).

    archive 不存在 → 新建 (手动补录日, akshare 没成功写 archive, 这是常见情况).
    archive 存在 → 读出来, manual 字段覆盖, 写回 (atomic: .tmp + rename).
    """
    path = _archive_path(trading_date)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                existing = {}
        except Exception as exc:
            logger.warning("read existing archive %s failed: %s", path, exc)
            existing = {}

    # manual 字段覆盖 archive 同名字段 (None 不覆盖, 保留 archive 原值)
    for k, v in cleaned.items():
        if v is not None:
            existing[k] = v

    # 元数据: tradingDate / source 标记
    existing["tradingDate"] = trading_date
    original_source = existing.get("source") or "unknown"
    existing["source"] = f"manual+{original_source}"
    existing["manualMergedAt"] = datetime.now().isoformat(timespec="seconds")

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    logger.info(
        "manual fund flow merged into archive: %s (fields=%d, source=%s)",
        path.name, len(cleaned), existing["source"],
    )


def save_manual_fund_flow(trading_date: str, fields: dict[str, Any]) -> dict[str, Any]:
    """保存手动粘贴的资金流数据. 覆盖式写入 (同日多次保存取最后一次).

    同时 merge 进 reference/market-overview/archive/<date>.json, 让"市场脉搏"资金潮汐/
    资金结构 趋势图立刻能读到 manual 数据 (不再走 fallback 链).

    Args:
        trading_date: YYYY-MM-DD
        fields: {mainNetInflow, mainNetInflowRatio, superLargeNetInflow, ...}
                不要求全部, 缺失字段保留 None (前端展示 "—")

    Returns:
        落盘后的完整 payload.
    """
    # 只接受这 10 个字段, 防止前端误传脏数据
    allowed = set(_MANUAL_MERGE_FIELDS)
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

    # 同步 merge 进 archive, 让 market-pulse 资金潮汐/资金结构 趋势图直接读到
    if cleaned:
        _merge_into_archive(trading_date, cleaned)

    # 同步写 PG (非致命)
    try:
        from backend.services.stock._pg_writer import upsert_overview_to_pg

        # 构造一个兼容的 payload (manual 字段只有资金流, 不包含 totalAmount/涨跌家数)
        manual_payload = {
            "tradingDate": trading_date,
            **cleaned,
        }
        upsert_overview_to_pg(manual_payload, source_tag="manual")
    except Exception as exc:
        logger.debug("upsert_overview_to_pg failed (non-fatal): %s", exc)

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
