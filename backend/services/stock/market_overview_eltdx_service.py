r"""市场概况数据服务 (eltdx 通达信协议).

维护前请先看:
`F:\dev-repo\mp4-to-word-new\design\backend\market-overview-json-to-postgres.md`

数据来源: eltdx (TCP 直连, 不走 HTTP, 不受代理/HTTP 限制)
覆盖范围: 全A成交额 / 涨跌家数 / 涨停跌停数 / 股票只数

运行时真源已经收口到 PostgreSQL: capture 只写 PG，latest/archive 读取由 API
直接走 PG，不再依赖 JSON 持久化.

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

from backend.config.database import session_scope
from backend.repositories.market.market_overview_pg_repo import MarketOverviewPgRepository

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
BASE = Path(__file__).resolve().parent.parent.parent.parent / "reference"
OVERVIEW_DIR = BASE / "market-overview"
OVERVIEW_LATEST_FILE = OVERVIEW_DIR / "market-overview" / "latest.json"
OVERVIEW_ARCHIVE_DIR = OVERVIEW_DIR / "market-overview" / "archive"
MARKET_LIMIT_DAILY_DIR = BASE / "market-limit" / "daily"


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _today_str() -> str:
    return _beijing_now().strftime("%Y-%m-%d")


def _archive_path_for(trading_date: str) -> Path:
    return OVERVIEW_ARCHIVE_DIR / f"{trading_date.replace('-', '')}.json"


# ---------------------------------------------------------------------------
# 上一交易日 PG 数据 (给前端算 diff)
# ---------------------------------------------------------------------------
def _load_eltdx_prev_day_overview(target_trading_date: str) -> dict | None:
    """读上一个交易日的 PG row, 返回 totalAmount 等字段."""
    with session_scope() as db:
        repo = MarketOverviewPgRepository(db)
        prev_row = repo.get_previous(target_trading_date)
    if not prev_row or prev_row.get("total_amount") is None:
        return None
    return {
        "prevDayTradingDate": prev_row.get("trade_date"),
        "prevDayTotalAmount": prev_row.get("total_amount"),
        "prevDaySource": prev_row.get("source") or "postgres",
    }


def _save_overview_to_archive(
    payload: dict,
    trading_date: str,
) -> None:
    """兼容保留的空实现: 运行时已不再写 JSON archive."""
    return None


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
    """把 eltdx overview 数据写入 PostgreSQL."""
    with _write_lock:
        trading_date = payload.get("tradingDate") or _today_str()
        if payload.get("totalAmount") is None:
            logger.info("eltdx overview 无实质数据 (totalAmount=None), 跳过 PG 写入")
            return

        eltdx_prev = _load_eltdx_prev_day_overview(trading_date)
        if eltdx_prev:
            payload["prevDayTotalAmount"] = eltdx_prev.get("prevDayTotalAmount")
            payload["prevDayTradingDate"] = eltdx_prev.get("prevDayTradingDate")

        from backend.services.stock._pg_writer import upsert_overview_to_pg

        upsert_overview_to_pg(payload, source_tag="eltdx")
        logger.info("eltdx overview saved to pg: %s", trading_date)


# ---------------------------------------------------------------------------
# 读取 latest (PG-only)
# ---------------------------------------------------------------------------
def get_latest_overview() -> dict:
    """从 PostgreSQL 读取最新 eltdx overview，并保留涨跌停 daily 覆盖口径."""
    today = _today_str()
    with session_scope() as db:
        repo = MarketOverviewPgRepository(db)
        chosen = repo.get_latest(today)

    if not chosen:
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
            "prevDayTotalAmount": None,
            "prevDayTradingDate": None,
        }

    payload = {
        "totalAmount": chosen.get("total_amount"),
        "totalVolume": chosen.get("total_volume"),
        "risingCount": chosen.get("rising_count"),
        "fallingCount": chosen.get("falling_count"),
        "flatCount": chosen.get("flat_count"),
        "limitUpCount": chosen.get("limit_up_count"),
        "limitDownCount": chosen.get("limit_down_count"),
        "stockCount": chosen.get("stock_count"),
        "tradingDate": chosen.get("trade_date"),
        "fetchedAt": chosen.get("updated_at"),
        "prevDayTotalAmount": None,
        "prevDayTradingDate": None,
    }

    eltdx_prev = _load_eltdx_prev_day_overview(payload.get("tradingDate") or today)
    if eltdx_prev:
        payload["prevDayTotalAmount"] = eltdx_prev.get("prevDayTotalAmount")
        payload["prevDayTradingDate"] = eltdx_prev.get("prevDayTradingDate")

    trading_date = payload.get("tradingDate") or today
    daily_path = MARKET_LIMIT_DAILY_DIR / f"{trading_date}.json"
    if daily_path.exists():
        try:
            daily_blob = json.loads(daily_path.read_text(encoding="utf-8"))
            stocks = daily_blob.get("stocks") or []
            if stocks:
                from backend.services.stock.limit_emotion_service import (
                    _apply_filters, _is_st, _infer_exchange_from_bare_code, _load_universe_meta,
                )
                universe_meta = _load_universe_meta()
                as_quotes: list[dict] = []
                for s in stocks:
                    code = (s.get("code") or "").lower()
                    name = s.get("name") or ""
                    meta = universe_meta.get(code) or {}
                    is_st_flag = bool(
                        s.get("isST") or _is_st(name) or meta.get("is_st", False)
                    )
                    as_quotes.append({
                        "code": code,
                        "last_price": s.get("latestPrice"),
                        "pre_close_price": None,
                        "change_pct": s.get("changePct"),
                        "high_price": s.get("highPrice"),
                        "exchange": (meta.get("exchange") or _infer_exchange_from_bare_code(code)).lower(),
                        "is_st": is_st_flag,
                        "is_new": bool(meta.get("is_new", False)),
                        "is_suspended": not (s.get("latestPrice") and float(s.get("latestPrice") or 0) > 0),
                    })
                from backend.services.stock.limit_emotion_service import DEFAULT_CONFIG
                filtered = _apply_filters(as_quotes, DEFAULT_CONFIG)
                keep_codes = {q["code"] for q in filtered}
                stocks_filtered = [s for s in stocks if (s.get("code") or "").lower() in keep_codes]
                payload["limitUpCount"] = sum(1 for s in stocks_filtered if s.get("isLimitUp"))
                payload["limitDownCount"] = sum(1 for s in stocks_filtered if s.get("isLimitDown"))
        except Exception as exc:
            logger.debug("read daily %s for limit counts failed: %s", daily_path, exc)

    return payload


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
