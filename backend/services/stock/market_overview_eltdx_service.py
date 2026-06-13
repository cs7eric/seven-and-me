"""市场概况数据服务 (eltdx 通达信协议).

数据来源: eltdx (TCP 直连, 不走 HTTP, 不受代理/HTTP 限制)
覆盖范围: 全A成交额 / 涨跌家数 / 涨停跌停数 / 股票只数

持久化结构:
  reference/market-overview/market-overview/
    latest.json          ← 最新一次成功 snapshot (atomic write)
    archive/
      YYYYMMDD.json    ← 按交易日归档

两个独立维度:
  1. eastmoney fund flow → reference/market-overview/fund-flow/latest.json
  2. eltdx market overview → reference/market-overview/market-overview/latest.json

互不覆盖, 任一数据源失败不影响另一方的持久化数据.

不修改既有的 market_overview_akshare_service.py (那是 fund flow).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from eltdx import TdxClient  # type: ignore[attr-defined]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
BASE = Path(__file__).resolve().parent.parent.parent.parent / "reference"
OVERVIEW_DIR = BASE / "market-overview"
OVERVIEW_LATEST_FILE = OVERVIEW_DIR / "market-overview" / "latest.json"
OVERVIEW_ARCHIVE_DIR = OVERVIEW_DIR / "market-overview" / "archive"


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _today_str() -> str:
    return _beijing_now().strftime("%Y-%m-%d")


def _archive_path_for(trading_date: str) -> Path:
    return OVERVIEW_ARCHIVE_DIR / f"{trading_date.replace('-', '')}.json"


# ---------------------------------------------------------------------------
# 归档持久化 (给 archive 使用, 共享 tradingDate/prevDayFlow)
# ---------------------------------------------------------------------------
def _save_overview_to_archive(
    payload: dict,
    trading_date: str,
) -> None:
    """把 eltdx 数据追加写入 archive (reference/market-overview/archive/<date>.json).

    archive 的 prevDayFlow 由 fund-flow 模块维护 (独立).
    这里只写 eltdx 自己的字段, 不动 prevDayFlow.
    """
    OVERVIEW_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    arch_path = _archive_path_for(trading_date)

    # 已有 archive, 合并 (不覆盖 fund-flow 已有的字段)
    if arch_path.exists():
        existing = json.loads(arch_path.read_text(encoding="utf-8"))
        # 只更新 eltdx 相关字段
        eltdx_fields = {
            "totalAmount", "totalVolume", "risingCount", "fallingCount",
            "flatCount", "limitUpCount", "limitDownCount", "stockCount",
        }
        for k, v in payload.items():
            if k in eltdx_fields:
                existing[k] = v
        payload = existing
    else:
        # 新建, 补 prevDayFlow 引用 (从 fund-flow archive 读)
        fund_arch = OVERVIEW_DIR / "fund-flow" / "archive" / f"{trading_date.replace('-', '')}.json"
        if fund_arch.exists():
            fund_data = json.loads(fund_arch.read_text(encoding="utf-8"))
            payload["prevDayFlow"] = fund_data.get("prevDayFlow")
            payload["prevDayTradingDate"] = fund_data.get("prevDayTradingDate")

    tmp = arch_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(arch_path)
    logger.info("eltdx overview archive saved: %s", arch_path.name)


# ---------------------------------------------------------------------------
# 拉 eltdx 全A数据
# ---------------------------------------------------------------------------
def fetch_overview() -> dict | None:
    """拉取全A实时概况 (eltdx).

    Returns:
        dict with keys: totalAmount, risingCount, fallingCount, flatCount,
        limitUpCount, limitDownCount, stockCount, tradingDate, fetchedAt
        失败返回 None (不抛异常, 由调用方决定 fallback).
    """
    try:
        t0 = time.time()
        with TdxClient(timeout=20.0) as client:
            codes = client.get_a_share_codes_all()
            quotes = client.get_quote(codes)

        rising = falling = flat = limit_up = limit_down = 0
        total_amount = 0.0
        stock_cnt = 0

        for q in quotes:
            stock_cnt += 1
            amt = getattr(q, "amount", None) or 0
            total_amount += float(amt)
            last = getattr(q, "last_price", None)
            prev = getattr(q, "pre_close_price", None)
            if last is None or prev is None or prev == 0:
                continue
            pct = (last - prev) / prev * 100
            if pct > 0:
                rising += 1
            elif pct < 0:
                falling += 1
            else:
                flat += 1
            if pct >= 9.5:
                limit_up += 1
            elif pct <= -9.5:
                limit_down += 1

        payload = {
            "totalAmount": round(total_amount / 1e8, 2),
            "risingCount": rising,
            "fallingCount": falling,
            "flatCount": flat,
            "limitUpCount": limit_up,
            "limitDownCount": limit_down,
            "stockCount": stock_cnt,
            "tradingDate": _today_str(),
            "fetchedAt": _beijing_now().isoformat(timespec="seconds"),
        }
        logger.info(
            "eltdx overview OK: totalAmount=%.2f亿, rising=%d, falling=%d, elapsed=%.1fs",
            payload["totalAmount"], rising, falling, time.time() - t0,
        )
        return payload
    except Exception as exc:
        logger.warning("eltdx overview fetch failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# 落盘 (独立, 不碰 fund-flow 的 latest.json)
# ---------------------------------------------------------------------------
_write_lock = threading.Lock()


def save_overview(payload: dict) -> None:
    """把 eltdx overview 数据落盘 (archive 永远写, latest 只在有数据时覆盖).

    不修改 reference/market-overview/fund-flow/ 下的任何文件.
    """
    with _write_lock:
        trading_date = payload.get("tradingDate") or _today_str()
        OVERVIEW_LATEST_FILE.parent.mkdir(parents=True, exist_ok=True)

        # 1) archive (永远写, 合并不覆盖)
        _save_overview_to_archive(payload, trading_date)

        # 2) latest (有实质数据才覆盖)
        if payload.get("totalAmount") is not None:
            tmp = OVERVIEW_LATEST_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(OVERVIEW_LATEST_FILE)
            logger.info("eltdx overview latest saved: %s", OVERVIEW_LATEST_FILE.name)
        else:
            logger.info(
                "eltdx overview 无实质数据 (totalAmount=None), latest.json 保留旧内容"
            )


# ---------------------------------------------------------------------------
# 读取 latest (带 archive fallback)
# ---------------------------------------------------------------------------
def get_latest_overview() -> dict:
    """读 eltdx overview latest, fallback 到 archive 同日, 再 fallback 到上一交易日."""
    # 1) latest
    if OVERVIEW_LATEST_FILE.exists():
        try:
            data = json.loads(OVERVIEW_LATEST_FILE.read_text(encoding="utf-8"))
            if data.get("totalAmount") is not None:
                return data
        except Exception:
            pass

    # 2) archive 同日
    today = _today_str()
    arch = _archive_path_for(today)
    if arch.exists():
        try:
            data = json.loads(arch.read_text(encoding="utf-8"))
            if data.get("totalAmount") is not None:
                return data
        except Exception:
            pass

    # 3) archive 上一交易日
    for offset in range(1, 15):
        candidate = (_beijing_now() - timedelta(days=offset)).date()
        arch2 = OVERVIEW_ARCHIVE_DIR / f"{candidate.strftime('%Y%m%d')}.json"
        if arch2.exists():
            try:
                data = json.loads(arch2.read_text(encoding="utf-8"))
                if data.get("totalAmount") is not None:
                    return data
            except Exception:
                pass

    # 4) 全挂: 返回空壳
    return {
        "totalAmount": None,
        "risingCount": None,
        "fallingCount": None,
        "flatCount": None,
        "limitUpCount": None,
        "limitDownCount": None,
        "stockCount": None,
        "tradingDate": None,
        "fetchedAt": None,
    }


# ---------------------------------------------------------------------------
# 对外入口: 拉取 + 落盘
# ---------------------------------------------------------------------------
def capture_overview(*, force: bool = False) -> dict | None:
    """拉取 eltdx overview 并落盘.

    失败返回 None (不抛异常).
    """
    payload = fetch_overview()
    if payload is None:
        return None
    save_overview(payload)
    return payload
