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
MARKET_LIMIT_DAILY_DIR = BASE / "market-limit" / "daily"


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _today_str() -> str:
    return _beijing_now().strftime("%Y-%m-%d")


def _archive_path_for(trading_date: str) -> Path:
    return OVERVIEW_ARCHIVE_DIR / f"{trading_date.replace('-', '')}.json"


# ---------------------------------------------------------------------------
# 归档持久化 (给 archive 使用, 共享 tradingDate/prevDayFlow)
# ---------------------------------------------------------------------------
def _load_eltdx_prev_day_overview(target_trading_date: str) -> dict | None:
    """读上一个交易日的 eltdx archive, 返回 totalAmount 等字段.

    给 eltdx latest.json / archive 算 ``prevDayTotalAmount`` 用.
    找不到返 None, 调用方按 missing 处理 (frontend 显示 "—").

    Fallback 链: eltdx 同日 archive (口径最准) → fund-flow 同日 archive (口径近似).
    后者只在前者缺失时用, 比如 eltdx scheduler 某天没跑, fund-flow 当天有数据
    (akshare spot_em 跑通), 用它先顶上去, 至少能让 diff 算个大概.
    """
    from backend.services.stock.trading_calendar import previous_trading_day
    try:
        target = datetime.strptime(target_trading_date, "%Y-%m-%d").date()
    except Exception:
        return None
    prev_date = previous_trading_day(target)
    prev_iso = prev_date.isoformat()

    # 1) 优先 eltdx 同日 archive
    eltdx_arch = _archive_path_for(prev_iso)
    if eltdx_arch.exists():
        try:
            data = json.loads(eltdx_arch.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("totalAmount") is not None:
                return {
                    "prevDayTradingDate": prev_iso,
                    "prevDayTotalAmount": data.get("totalAmount"),
                    "prevDaySource": "eltdx",
                }
        except Exception:
            pass

    # 2) Fallback: fund-flow 同日 archive 的 totalAmount (口径不同但能算 diff 方向)
    fund_arch = OVERVIEW_DIR / "fund-flow" / "archive" / f"{prev_date.strftime('%Y%m%d')}.json"
    if fund_arch.exists():
        try:
            data = json.loads(fund_arch.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("totalAmount") is not None:
                return {
                    "prevDayTradingDate": prev_iso,
                    "prevDayTotalAmount": data.get("totalAmount"),
                    "prevDaySource": "fund-flow",
                }
        except Exception:
            pass

    return None


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
            "prevDayTotalAmount", "prevDayTradingDate",
        }
        for k, v in payload.items():
            if k in eltdx_fields:
                existing[k] = v
        payload = existing
    else:
        # 新建, 补 eltdx 自己的 prevDayTotalAmount (从上一交易日 eltdx archive 读).
        # 不要从 fund-flow 的 prevDayFlow 拷 totalAmount: akshare 失败时该字段是 null,
        # 跟 eltdx 的 totalAmount 不是同一口径, 算 diff 会得到错的数.
        eltdx_prev = _load_eltdx_prev_day_overview(trading_date)
        if eltdx_prev:
            payload["prevDayTotalAmount"] = eltdx_prev.get("prevDayTotalAmount")
            payload["prevDayTradingDate"] = eltdx_prev.get("prevDayTradingDate")

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

        # 1) archive (永远写, 合并不覆盖). archive 内会算 prevDayTotalAmount.
        _save_overview_to_archive(payload, trading_date)

        # 2) latest (有实质数据才覆盖). 把 prevDayTotalAmount 也带上, 让前端
        #    "大盘成交额 较昨日" 在 akshare 失败时 (overview.prevDayFlow.totalAmount=null)
        #    仍能用 eltdx 自己的口径算 diff.
        if payload.get("totalAmount") is not None:
            if "prevDayTotalAmount" not in payload:
                eltdx_prev = _load_eltdx_prev_day_overview(trading_date)
                if eltdx_prev:
                    payload["prevDayTotalAmount"] = eltdx_prev.get("prevDayTotalAmount")
                    payload["prevDayTradingDate"] = eltdx_prev.get("prevDayTradingDate")
            tmp = OVERVIEW_LATEST_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(OVERVIEW_LATEST_FILE)
            logger.info("eltdx overview latest saved: %s", OVERVIEW_LATEST_FILE.name)

            # 顺手落 duckdb (字段级 upsert, 已有 akshare 字段不覆盖)
            try:
                from backend.repositories.market.market_overview_repo import upsert_overview_eltdx
                upsert_overview_eltdx(payload)
            except Exception as exc:
                logger.debug("upsert_overview_eltdx to duckdb failed (non-fatal): %s", exc)
        else:
            logger.info(
                "eltdx overview 无实质数据 (totalAmount=None), latest.json 保留旧内容"
            )


# ---------------------------------------------------------------------------
# 读取 latest (带 archive fallback)
# ---------------------------------------------------------------------------
def get_latest_overview() -> dict:
    """读 eltdx overview latest, fallback 到 archive 同日, 再 fallback 到上一交易日.

    limitUpCount / limitDownCount: 优先用 market-limit/daily/<date>.json (跟涨跌停情绪面板
    走同一份 daily file, 涨跌停口径一致 — 用各板块 9.95/19.95/29.95/4.95 阈值,
    不是 eltdx overview 自己的 9.5% 宽松口径). daily file 缺失才回退到 eltdx 算的.
    """
    candidates: list[dict] = []

    # 1) latest
    if OVERVIEW_LATEST_FILE.exists():
        try:
            data = json.loads(OVERVIEW_LATEST_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("totalAmount") is not None:
                candidates.append(data)
        except Exception:
            pass

    # 2) archive 同日
    today = _today_str()
    arch = _archive_path_for(today)
    if arch.exists():
        try:
            data = json.loads(arch.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("totalAmount") is not None:
                candidates.append(data)
        except Exception:
            pass

    # 3) archive 上一交易日
    for offset in range(1, 15):
        candidate = (_beijing_now() - timedelta(days=offset)).date()
        arch2 = OVERVIEW_ARCHIVE_DIR / f"{candidate.strftime('%Y%m%d')}.json"
        if arch2.exists():
            try:
                data = json.loads(arch2.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("totalAmount") is not None:
                    candidates.append(data)
            except Exception:
                pass

    if not candidates:
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
            "prevDayTotalAmount": None,
            "prevDayTradingDate": None,
        }

    # 取优先级最高的, 但用 archive 同日补 prevDayTotalAmount (老 archive 没这字段)
    chosen = candidates[0]
    if "prevDayTotalAmount" not in chosen:
        trading_date = chosen.get("tradingDate") or today
        eltdx_prev = _load_eltdx_prev_day_overview(trading_date)
        if eltdx_prev:
            chosen["prevDayTotalAmount"] = eltdx_prev.get("prevDayTotalAmount")
            chosen["prevDayTradingDate"] = eltdx_prev.get("prevDayTradingDate")
        else:
            chosen.setdefault("prevDayTotalAmount", None)
            chosen.setdefault("prevDayTradingDate", None)

    # limitUp/limitDown: 用 market-limit/daily/<tradingDate>.json 的准确数 (跟涨跌停情绪面板一致).
    # eltdx 自己的 limitUp/limitDown 用 9.5% 宽松口径 (不区分板块), 跟涨跌停情绪不一致 —
    # 涨跌停情绪用 9.95/19.95/29.95/4.95 (板块区分) + isLimitUp 字段. 优先用 daily file 覆盖.
    # 同样过 limit_emotion 的 config 过滤 (excludeST 默认 True, excludeNewStock 默认 False),
    # 这样 大盘卡片 跟 涨跌停面板 显示同一份数 (不会 142 vs 113 打架).
    trading_date = chosen.get("tradingDate") or today
    daily_path = MARKET_LIMIT_DAILY_DIR / f"{trading_date}.json"
    if daily_path.exists():
        try:
            daily_blob = json.loads(daily_path.read_text(encoding="utf-8"))
            stocks = daily_blob.get("stocks") or []
            if stocks:
                # 跟 涨跌停面板 同口径 — 走 limit_emotion_service._apply_filters
                # is_st 二次用 universe meta 确认, 跟 _aggregate_from_daily 一致
                # (避免 name 缺失导致漏判 ST / 新股)
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
                # 用跟 limit_emotion_service 一样的默认 config (跟 _load_config 行为一致)
                # _load_config 合并 DEFAULT_CONFIG, 这里直接 inline:
                from backend.services.stock.limit_emotion_service import DEFAULT_CONFIG
                filtered = _apply_filters(as_quotes, DEFAULT_CONFIG)
                keep_codes = {q["code"] for q in filtered}
                stocks_filtered = [s for s in stocks if (s.get("code") or "").lower() in keep_codes]
                up_n = sum(1 for s in stocks_filtered if s.get("isLimitUp"))
                dn_n = sum(1 for s in stocks_filtered if s.get("isLimitDown"))
                chosen["limitUpCount"] = up_n
                chosen["limitDownCount"] = dn_n
        except Exception as exc:
            logger.debug("read daily %s for limit counts failed: %s", daily_path, exc)

    return chosen


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
