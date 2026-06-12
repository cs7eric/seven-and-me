"""大盘成交额 / 主力净流入 持久化服务 (AKShare 双源).

**不修改**既有的 :mod:`backend.services.stock.market_overview_service`
(那是 K线技术分析模块, 跟本模块职责不同, 不要动).

本模块职责:
- **盘中实时**: AKShare ``stock_zh_a_spot_em()`` 汇总全 A 成交额/成交量
  + ``stock_market_fund_flow()`` 拉大盘主力净流入 (东方财富口径)
- **盘后 / 离线归档**: ``reference/market-overview/archive/<YYYY-MM-DD>.json``
  按交易日归档; ``latest.json`` 永远指向最近一次成功 snapshot

调用方:
- scheduler (:mod:`backend.services.scheduler.market_overview_scheduler`):
  盘内 5 分钟一次 + 15:35 收盘后落盘 + 09:00 开盘前 warmup
- API: ``GET /api/stock-chart/market-overview/akshare``
        ``POST /api/stock-chart/market-overview/akshare/refresh``
        ``GET /api/stock-chart/market-overview/akshare/scheduler/status``
        ``GET /api/stock-chart/market-overview/akshare/archive/<date>``

字段约定:
- ``totalAmount``      全 A 成交额 (单位: 亿元)
- ``totalVolume``      全 A 成交量 (单位: 万手)
- ``risingCount``      上涨家数
- ``fallingCount``     下跌家数
- ``flatCount``        平盘家数
- ``limitUpCount``     涨停家数 (zdf ≥ 9.5%)
- ``limitDownCount``   跌停家数 (zdf ≤ -9.5%)
- ``mainNetInflow``    主力净流入 (单位: 亿元) — 东方财富推算口径, **非交易所官方**
- ``superLargeNetInflow``   超大单净流入 (亿元)
- ``largeNetInflow``        大单净流入 (亿元)
- ``mediumNetInflow``       中单净流入 (亿元)
- ``smallNetInflow``        小单净流入 (亿元)
- ``source``           "akshare" | "archived"
- ``fetchedAt``        拉数据时间 (ISO8601 北京时间)
- ``tradingDate``      交易日 (YYYY-MM-DD)
"""
from __future__ import annotations

import json
import logging
import threading
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from backend.config.settings import (
    MARKET_OVERVIEW_ARCHIVE_DIR,
    MARKET_OVERVIEW_FOLDER,
    MARKET_OVERVIEW_LATEST_FILE,
)
from backend.services.stock.trading_calendar import (
    is_trade_time,
    is_trading_day,
)
from backend.utils.json_io import read_json_file

logger = logging.getLogger(__name__)

# 拉取超时 (秒). AKShare 偶尔会卡 30s+, 给个硬上限避免阻塞 scheduler.
AKSHARE_TIMEOUT_SECONDS = 30


def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _today_str() -> str:
    return _beijing_now().date().isoformat()


# ---------------------------------------------------------------------------
# AKShare 拉取
# ---------------------------------------------------------------------------
def _fetch_from_akshare() -> dict[str, Any] | None:
    """拉一次 AKShare 实时大盘数据, 失败返回 None.

    包含两路:
    - ``stock_zh_a_spot_em()``   全 A 实时行情 -> 汇总 totalAmount/totalVolume/risingCount/...
    - ``stock_market_fund_flow()``  东方财富资金流 -> mainNetInflow/superLarge/large/medium/small
    """
    try:
        import akshare as ak
    except ImportError as exc:
        logger.warning("akshare 未安装: %s", exc)
        return None

    out: dict[str, Any] = {
        "totalAmount": None,
        "totalVolume": None,
        "risingCount": None,
        "fallingCount": None,
        "flatCount": None,
        "limitUpCount": None,
        "limitDownCount": None,
        "mainNetInflow": None,
        "superLargeNetInflow": None,
        "largeNetInflow": None,
        "mediumNetInflow": None,
        "smallNetInflow": None,
        "stockCount": None,
    }

    # --- 路 1: 全 A 实时行情 (东方财富) ---
    try:
        t0 = time.time()
        spot = ak.stock_zh_a_spot_em()
        if spot is not None and not spot.empty:
            # 字段通常: 序号 代码 名称 最新价 涨跌幅 涨跌额 成交量 成交额 振幅 换手率 ...
            zdf_col = None
            for c in spot.columns:
                if "涨跌幅" in str(c):
                    zdf_col = c
                    break
            amount_col = None
            for c in spot.columns:
                if "成交额" in str(c):
                    amount_col = c
                    break
            volume_col = None
            for c in spot.columns:
                if "成交量" in str(c) and "额" not in str(c):
                    volume_col = c
                    break

            def _num(series: pd.Series) -> pd.Series:
                return pd.to_numeric(series, errors="coerce").fillna(0)

            if amount_col:
                amounts = _num(spot[amount_col])
                out["totalAmount"] = round(float(amounts.sum()) / 1e8, 2)  # 元 -> 亿元
            if volume_col:
                volumes = _num(spot[volume_col])
                # 成交量单位是 "手" (1 手 = 100 股), 累加 = 万手
                out["totalVolume"] = round(float(volumes.sum()) / 1e4, 2)
            if zdf_col:
                zdfs = _num(spot[zdf_col])
                # 涨跌停推算: 普通股 ±10% 算 (创业板/科创板/北交所 ±20% / ±30%, 简化用 ±9.5%)
                out["risingCount"] = int((zdfs >= 0.5).sum())
                out["fallingCount"] = int((zdfs <= -0.5).sum())
                out["flatCount"] = int(((zdfs > -0.5) & (zdfs < 0.5)).sum())
                out["limitUpCount"] = int((zdfs >= 9.5).sum())
                out["limitDownCount"] = int((zdfs <= -9.5).sum())
            out["stockCount"] = int(len(spot))
        else:
            logger.warning("akshare stock_zh_a_spot_em 返回空")
        logger.info("akshare spot 拉取耗时 %.1fs", time.time() - t0)
    except Exception as exc:
        logger.warning("akshare stock_zh_a_spot_em 失败: %s\n%s", exc, traceback.format_exc())

    # --- 路 2: 东方财富大盘资金流 ---
    try:
        t0 = time.time()
        flow = ak.stock_market_fund_flow()
        if flow is not None and not flow.empty:
            latest = flow.tail(1).iloc[0]
            # 字段: 主力净流入-净额 / 主力净流入-净占比 / 超大单净流入-净额 / 大单净流入-净额 /
            #       中单净流入-净额 / 小单净流入-净额
            def _col(name_suffix: str) -> float | None:
                for c in flow.columns:
                    if str(c).endswith(name_suffix) and "占比" not in str(c):
                        v = pd.to_numeric(pd.Series([latest[c]]), errors="coerce").iloc[0]
                        if pd.isna(v):
                            return None
                        # 该字段是万元, 转为亿元
                        return round(float(v) / 1e4, 2)
                return None

            out["mainNetInflow"] = _col("主力净流入-净额")
            out["superLargeNetInflow"] = _col("超大单净流入-净额")
            out["largeNetInflow"] = _col("大单净流入-净额")
            out["mediumNetInflow"] = _col("中单净流入-净额")
            out["smallNetInflow"] = _col("小单净流入-净额")
        else:
            logger.warning("akshare stock_market_fund_flow 返回空")
        logger.info("akshare flow 拉取耗时 %.1fs", time.time() - t0)
    except Exception as exc:
        logger.warning("akshare stock_market_fund_flow 失败: %s\n%s", exc, traceback.format_exc())

    # 任何一路都不行 -> 整体失败
    if out["totalAmount"] is None and out["mainNetInflow"] is None:
        return None
    return out


# ---------------------------------------------------------------------------
# 落盘
# ---------------------------------------------------------------------------
def _save_snapshot(payload: dict[str, Any]) -> Path:
    """把一次 snapshot 落到:
      - reference/market-overview/latest.json (pointer, atomic)
      - reference/market-overview/archive/<tradingDate>.json (按天归档)

    atomic write: 写 .tmp 再 rename, 避免读到半截文件.
    """
    MARKET_OVERVIEW_FOLDER.mkdir(parents=True, exist_ok=True)
    MARKET_OVERVIEW_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    # 1) latest.json — atomic
    tmp_latest = MARKET_OVERVIEW_LATEST_FILE.with_suffix(".json.tmp")
    with tmp_latest.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp_latest.replace(MARKET_OVERVIEW_LATEST_FILE)

    # 2) archive 按 tradingDate 命名
    trading_date = (payload.get("tradingDate") or _today_str()).replace("-", "")
    archive_path = MARKET_OVERVIEW_ARCHIVE_DIR / f"{trading_date}.json"
    tmp_arch = archive_path.with_suffix(".json.tmp")
    with tmp_arch.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp_arch.replace(archive_path)
    return archive_path


def _archive_path_for(trading_date: str) -> Path:
    return MARKET_OVERVIEW_ARCHIVE_DIR / f"{trading_date.replace('-', '')}.json"


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
_write_lock = threading.Lock()


def capture_snapshot(*, force: bool = False, source: str = "akshare") -> dict[str, Any] | None:
    """拉一次数据并落盘. 交易时间内任意时间可调; 盘后只允许 force=True (兜底补落).

    返回写入的 payload (含 source/fetchedAt/tradingDate), 失败返回 None.
    """
    with _write_lock:
        now = _beijing_now()
        if not force and not is_trade_time(now):
            logger.debug("akshare market_overview snapshot skipped: not trade time")
            return None
        if not force and not is_trading_day(now.date()):
            logger.debug("akshare market_overview snapshot skipped: not trading day")
            return None

        fetched: dict[str, Any] | None = None
        if source == "akshare":
            fetched = _fetch_from_akshare()
        if fetched is None:
            logger.warning("akshare market_overview snapshot 拉取失败, 跳过本次落盘")
            return None

        trading_date = _today_str()
        payload = {
            **fetched,
            "tradingDate": trading_date,
            "fetchedAt": now.isoformat(timespec="seconds"),
            "source": "akshare",
            "isTradeTime": is_trade_time(now),
        }
        archive = _save_snapshot(payload)
        logger.info(
            "akshare market_overview snapshot saved: %s (amt=%s, main=%.2f亿)",
            archive,
            payload.get("totalAmount"),
            payload.get("mainNetInflow") or 0,
        )
        return payload


def get_latest_snapshot() -> dict[str, Any]:
    """读 latest snapshot (前端 API 用).

    优先级: latest.json > 同日 archive > 上一交易日 archive.
    """
    if MARKET_OVERVIEW_LATEST_FILE.exists():
        data = read_json_file(MARKET_OVERVIEW_LATEST_FILE, None)
        if isinstance(data, dict):
            data.setdefault("source", "archived")
            return data

    # 兜底: 找 archive 里最近一天
    if MARKET_OVERVIEW_ARCHIVE_DIR.exists():
        files = sorted(
            MARKET_OVERVIEW_ARCHIVE_DIR.glob("*.json"),
            key=lambda p: p.name,
            reverse=True,
        )
        if files:
            data = read_json_file(files[0], None)
            if isinstance(data, dict):
                data.setdefault("source", "archived")
                return data

    return {
        "ok": False,
        "error": "no akshare market overview snapshot found",
        "tradingDate": _today_str(),
        "fetchedAt": None,
        "totalAmount": None,
        "mainNetInflow": None,
    }


def get_archived_snapshot(trading_date: str) -> dict[str, Any] | None:
    """按交易日读 archive (历史日期用)."""
    p = _archive_path_for(trading_date)
    if not p.exists():
        return None
    return read_json_file(p, None)


def list_archived_dates(limit: int = 60) -> list[str]:
    """列最近 N 个交易日的 archive 文件名 (YYYYMMDD)."""
    if not MARKET_OVERVIEW_ARCHIVE_DIR.exists():
        return []
    files = sorted(
        MARKET_OVERVIEW_ARCHIVE_DIR.glob("*.json"),
        key=lambda p: p.name,
        reverse=True,
    )
    return [p.stem for p in files[:limit]]
