from __future__ import annotations

"""大盘成交额 / 主力净流入 持久化服务 (AKShare 双源).

**不走系统代理**: akshare requests 默认读取 Windows WinHTTP/IE 系统代理设置,
如果代理软件没开或端口不对会超时/失败. 本模块在 import 时清空代理环境变量,
并通过 monkey-patch 让 ``requests.Session`` 默认 ``trust_env=False`` 直连,
不影响系统其他程序的代理配置.

**不修改**既有的 :mod:`backend.services.stock.market_overview_service`
(那是 K线技术分析模块, 跟本模块职责不同, 不要动).
"""

# ---------------------------------------------------------------------------
# 不走系统代理: 清空代理环境变量 + 让 requests 读 trust_env=False
# ---------------------------------------------------------------------------
import os as _os
# 清空代理环境变量 (不影响其他进程, 只影响当前 Python 进程)
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
          "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"):
    _os.environ.pop(_k, None)

import requests as _requests

def _no_proxy_session() -> _requests.Session:
    """返回一个不走系统代理的 requests Session."""
    s = _requests.Session()
    s.trust_env = False
    return s

# 全局 patch: 让 requests.Session 每次实例化的 trust_env 默认为 False
# 这样 akshare 内部创建的任何 Session 都不会走系统代理
_original_init = _requests.Session.__init__


def _patched_init(self, *args, **kwargs):
    _original_init(self, *args, **kwargs)
    self.trust_env = False


_requests.Session.__init__ = _patched_init

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

# ---------------------------------------------------------------------------
# 路径覆写: fund-flow 独立持久化, 不跟 eltdx overview 混用 latest.json
# ---------------------------------------------------------------------------
# fund-flow → reference/market-overview/fund-flow/latest.json (独立)
# eltdx overview → reference/market-overview/market-overview/latest.json (独立)
# archive 共用: reference/market-overview/archive/ (两方都写自己字段, 互不覆盖)
_MARKET_OVERVIEW_FOLDER = MARKET_OVERVIEW_FOLDER / "fund-flow"
_MARKET_OVERVIEW_LATEST_FILE = _MARKET_OVERVIEW_FOLDER / "latest.json"
# archive 保持共用 (不迁历史数据), fund-flow 和 eltdx 各自写自己的字段到 shared archive
_MARKET_OVERVIEW_ARCHIVE_DIR = MARKET_OVERVIEW_FOLDER / "archive"  # shared!

# 替换后续引用 (覆盖 settings 导入的同名变量)
MARKET_OVERVIEW_FOLDER = _MARKET_OVERVIEW_FOLDER  # noqa: N816
MARKET_OVERVIEW_LATEST_FILE = _MARKET_OVERVIEW_LATEST_FILE  # noqa: N816
MARKET_OVERVIEW_ARCHIVE_DIR = _MARKET_OVERVIEW_ARCHIVE_DIR  # noqa: N816
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

    # 注: totalAmount / risingCount 等市场概况字段由 eltdx service 独立拉取,
    # 此处不处理, fund-flow service 只管 eastmoney 资金流.

    # --- 路 2: 东方财富大盘资金流 ---
    try:
        t0 = time.time()
        flow = ak.stock_market_fund_flow()
        if flow is not None and not flow.empty:
            latest = flow.tail(1).iloc[0]
            # 字段: 主力净流入-净额 / 主力净流入-净占比 / 超大单净流入-净额 / 大单净流入-净额 /
            #       中单净流入-净额 / 小单净流入-净额
            def _round_sum(*vals: float | None) -> float | None:
                """None 不参与累加, 全 None 返回 None, 有值返回 sum 并 round 到 2 位."""
                non_none = [v for v in vals if v is not None]
                if not non_none:
                    return None
                return round(sum(non_none), 2)

            def _col(name_suffix: str) -> float | None:
                for c in flow.columns:
                    if str(c).endswith(name_suffix) and "占比" not in str(c):
                        v = pd.to_numeric(pd.Series([latest[c]]), errors="coerce").iloc[0]
                        if pd.isna(v):
                            return None
                        # AKShare 原始单位是元, 转亿元: / 1e8
                        return round(float(v) / 1e8, 2)
                return None

            def _ratio(name_suffix: str) -> float | None:
                """读 AKShare "-净占比" 字段, 本身就是 %, 直接返回 (保留 2 位小数)."""
                for c in flow.columns:
                    if str(c).endswith(name_suffix) and "占比" in str(c):
                        v = pd.to_numeric(pd.Series([latest[c]]), errors="coerce").iloc[0]
                        if pd.isna(v):
                            return None
                        return round(float(v), 2)
                return None

            out["superLargeNetInflow"] = _col("超大单净流入-净额")
            out["largeNetInflow"] = _col("大单净流入-净额")
            out["mediumNetInflow"] = _col("中单净流入-净额")
            out["smallNetInflow"] = _col("小单净流入-净额")
            # 东方财富口径: 主力净流入 = 超大单 + 大单
            out["mainNetInflow"] = _round_sum(
                out["superLargeNetInflow"], out["largeNetInflow"]
            )

            # 净比 (%): AKShare 直接带 "-净占比" 字段, 本身就是 %
            out["mainNetInflowRatio"] = _ratio("主力净流入-净占比")
            out["superLargeNetInflowRatio"] = _ratio("超大单净流入-净占比")
            out["largeNetInflowRatio"] = _ratio("大单净流入-净占比")
            out["mediumNetInflowRatio"] = _ratio("中单净流入-净占比")
            out["smallNetInflowRatio"] = _ratio("小单净流入-净占比")

            # DEBUG log 已删 (单位已确认: AKShare 原始单位是元, ÷1e8 正确)
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
# 昨日资金数据 (用于与今日差额对比)
# ---------------------------------------------------------------------------
# 资金流相关字段 (只存这些, payload 轻量化)
_FLOW_FIELDS = [
    "mainNetInflow",
    "superLargeNetInflow",
    "largeNetInflow",
    "mediumNetInflow",
    "smallNetInflow",
    "mainNetInflowRatio",
    "superLargeNetInflowRatio",
    "largeNetInflowRatio",
    "mediumNetInflowRatio",
    "smallNetInflowRatio",
    "totalAmount",
]


def _extract_flow_data(payload: dict[str, Any]) -> dict[str, Any] | None:
    """从 payload 里只提取资金流相关字段, 供前端算 vs-昨日差额用."""
    if not payload:
        return None
    return {k: payload.get(k) for k in _FLOW_FIELDS}


def _prev_trading_day() -> str | None:
    """返回上一个交易日的 YYYY-MM-DD (不含今日)."""
    from datetime import timedelta
    d = datetime.utcnow() + timedelta(hours=8)
    for offset in range(1, 15):  # 最多往前找 14 天
        candidate = (d - timedelta(days=offset)).date()
        if is_trading_day(candidate):
            return candidate.strftime("%Y-%m-%d")
    return None


# ---------------------------------------------------------------------------
# 落盘
# ---------------------------------------------------------------------------
def _save_snapshot(payload: dict[str, Any]) -> Path:
    """把一次 snapshot 落到:
      - reference/market-overview/archive/<tradingDate>.json (按天归档, 永远落)
      - reference/market-overview/latest.json (只在本轮有实质数据时才覆盖, 否则保留旧数据)

    实质数据判定: 有 mainNetInflow 或 totalAmount (任一即可, 说明 eastmoney/eltdx 任一数据源通了).
    archive 永远落盘 (保历史); latest 保守覆盖 (避免空数据把有效旧数据冲掉).

    atomic write: 写 .tmp 再 rename, 避免读到半截文件.
    """
    MARKET_OVERVIEW_FOLDER.mkdir(parents=True, exist_ok=True)
    MARKET_OVERVIEW_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    # 1) archive 按 tradingDate 命名 (永远落盘)
    trading_date = (payload.get("tradingDate") or _today_str()).replace("-", "")
    archive_path = MARKET_OVERVIEW_ARCHIVE_DIR / f"{trading_date}.json"
    tmp_arch = archive_path.with_suffix(".json.tmp")
    with tmp_arch.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp_arch.replace(archive_path)

    # 2) latest.json — fund-flow 独立检查, 只看 mainNetInflow
    #    (totalAmount 是 eltdx overview 的职责, 不混用 latest)
    has_main_data = payload.get("mainNetInflow") is not None
    if has_main_data:
        tmp_latest = MARKET_OVERVIEW_LATEST_FILE.with_suffix(".json.tmp")
        with tmp_latest.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        tmp_latest.replace(MARKET_OVERVIEW_LATEST_FILE)
    else:
        logger.info(
            "fund-flow snapshot 无实质数据 (mainNetInflow=None), "
            "fund-flow/latest.json 保留旧内容"
        )

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

        # 找上一交易日 archive, 把资金流数据塞进 payload 供前端算 vs-昨日差额
        prev_date = _prev_trading_day()
        if prev_date:
            prev_path = _archive_path_for(prev_date)
            if prev_path.exists():
                prev_data = read_json_file(prev_path, None)
                prev_flow = _extract_flow_data(prev_data)
                if prev_flow:
                    payload["prevDayFlow"] = prev_flow
                    payload["prevDayTradingDate"] = prev_date

        archive = _save_snapshot(payload)
        logger.info(
            "akshare market_overview snapshot saved: %s (amt=%s, main=%.2f亿, prevDay=%s)",
            archive,
            payload.get("totalAmount"),
            payload.get("mainNetInflow") or 0,
            payload.get("prevDayTradingDate") or "none",
        )
        return payload


def get_latest_snapshot() -> dict[str, Any]:
    """读 latest snapshot (前端 API 用).

    优先级: latest.json > 同日 archive > 上一交易日 archive.

    **isTradeTime 覆盖**: 持久化里的 ``isTradeTime`` 是 ``capture_snapshot()`` 上一次落盘时的值
    (e.g. 上一交易日 10:00 写入, 字段就是 ``true``); 现在重新算成"当前时间"的真实状态,
    否则非交易日 (周末 / 节假日) 拉到的 ``isTradeTime`` 永远是陈旧的 ``true``,
    前端 deck 顶部 pill 会错误显示 "今日实时 1m" 而非 "上次收盘".
    """
    if MARKET_OVERVIEW_LATEST_FILE.exists():
        data = read_json_file(MARKET_OVERVIEW_LATEST_FILE, None)
        if isinstance(data, dict):
            data.setdefault("source", "archived")
            data["isTradeTime"] = is_trade_time()
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
                data["isTradeTime"] = is_trade_time()
                return data

    return {
        "ok": False,
        "error": "no akshare market overview snapshot found",
        "tradingDate": _today_str(),
        "fetchedAt": None,
        "totalAmount": None,
        "mainNetInflow": None,
        "isTradeTime": is_trade_time(),
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


# ---------------------------------------------------------------------------
# 历史序列 (Market Pulse 历史趋势图用)
# ---------------------------------------------------------------------------
# 历史点只暴露前端需要的字段, 不把 prevDayFlow/ratios 等冗余字段透出去.
# 数值字段一律 nullable, archive 里早于 2026-05 的快照 totalAmount/risingCount
# 等 spot_em 字段可能是 null (旧版 capture_snapshot 不爬 spot_em), 前端按 null 渲染 "—".
_HISTORY_FIELDS = [
    "totalAmount",
    "totalVolume",
    "risingCount",
    "fallingCount",
    "flatCount",
    "limitUpCount",
    "limitDownCount",
    "mainNetInflow",
    "superLargeNetInflow",
    "largeNetInflow",
    "mediumNetInflow",
    "smallNetInflow",
]

# eltdx archive 路径: reference/market-overview/market-overview/archive/YYYYMMDD.json
# (akshare archive 是 reference/market-overview/archive/YYYYMMDD.json, 共享 dir 上层)
_ELTDX_ARCHIVE_DIR = MARKET_OVERVIEW_FOLDER / "market-overview" / "archive"
# manual 路径: reference/market-overview/fund-flow/manual/YYYYMMDD.json
_MANUAL_DIR = _MARKET_OVERVIEW_FOLDER / "manual"
# eltdx latest: reference/market-overview/market-overview/latest.json
_ELTDX_LATEST_FILE = MARKET_OVERVIEW_FOLDER / "market-overview" / "latest.json"


def _yyyymmdd_to_iso(stem: str) -> str | None:
    """'20260615' -> '2026-06-15'. 解析失败返 None."""
    if len(stem) != 8 or not stem.isdigit():
        return None
    return f"{stem[:4]}-{stem[4:6]}-{stem[6:8]}"


def _merge_point_fields(
    point: dict[str, Any],
    payload: dict[str, Any],
    fields: list[str],
    fallback_source: str,
) -> None:
    """把 payload 里的 fields 合并到 point (只填 point 当前为 None 的字段, 保留已有值).
    同时更新 source 标记, 表明该 point 至少有一条字段来自 fallback_source.
    """
    merged_any = False
    for f in fields:
        v = payload.get(f)
        if v is not None and point.get(f) is None:
            point[f] = v
            merged_any = True
    if merged_any:
        # 只在已经合并过 fallback 数据时, 把 source 标记成 fallback (避免覆盖已有 "eastmoney")
        existing = point.get("source")
        if existing != "eastmoney":
            point["source"] = fallback_source


def get_history_points(days: int = 60) -> list[dict[str, Any]]:
    """读最近 N 个交易日的历史序列, **多源合并** 后返回.

    数据源优先级 (同一字段先到先得, 后到的不覆盖):
      1. shared archive (``reference/market-overview/archive/YYYYMMDD.json``)
         —— akshare 写的, 含部分 eltdx 字段 (merge 依赖写入顺序, 不保证完整).
      2. eltdx archive (``reference/market-overview/market-overview/archive/``)
         —— 独立, 字段全 totalAmount / risingCount / 涨跌家数, akshare 失败时
            这条线依然有大盘成交额 / 涨跌温度, 至少让"市场脉搏"图表能延续到今天.
      3. manual fund flow (``reference/market-overview/fund-flow/manual/``)
         —— 用户粘贴, 含 mainNetInflow / 4 单 净流入 + 净比, akshare 资金流
            失败时这条线兜底.
      4. fund-flow/latest.json + eltdx latest.json (仅当 tradingDate = 今天,
         且对应日期还没在 archive 里出现过) —— 给"今天"一个 placeholder 点,
         避免图表最后一段空白.

    字段单位保持跟现有 archive / snapshot 一致:
      - 资金流相关字段 (mainNetInflow 等): 单位 "亿"
      - 成交额 (totalAmount): 单位 "亿"
      - 涨跌家数: 整数
    """
    points_by_date: dict[str, dict[str, Any]] = {}

    # 1) shared archive (akshare 写, 可能含部分 eltdx 字段)
    if MARKET_OVERVIEW_ARCHIVE_DIR.exists():
        files = sorted(
            MARKET_OVERVIEW_ARCHIVE_DIR.glob("*.json"),
            key=lambda p: p.name,
            reverse=True,
        )[: max(1, days)]
        for f in files:
            data = read_json_file(f, None)
            if not isinstance(data, dict):
                continue
            date_str = _yyyymmdd_to_iso(f.stem)
            if not date_str:
                continue
            point = points_by_date.setdefault(date_str, {"date": date_str})
            for field in _HISTORY_FIELDS:
                v = data.get(field)
                if v is not None and point.get(field) is None:
                    point[field] = v
            point.setdefault("source", "eastmoney")

    # 2) eltdx archive (独立, 字段 totalAmount / risingCount / 涨跌家数)
    if _ELTDX_ARCHIVE_DIR.exists():
        eltdx_fields = [
            "totalAmount", "totalVolume",
            "risingCount", "fallingCount", "flatCount",
            "limitUpCount", "limitDownCount", "stockCount",
        ]
        files = sorted(
            _ELTDX_ARCHIVE_DIR.glob("*.json"),
            key=lambda p: p.name,
            reverse=True,
        )[: max(1, days)]
        for f in files:
            data = read_json_file(f, None)
            if not isinstance(data, dict):
                continue
            date_str = _yyyymmdd_to_iso(f.stem)
            if not date_str:
                continue
            point = points_by_date.setdefault(date_str, {"date": date_str})
            _merge_point_fields(point, data, eltdx_fields, "eltdx")

    # 3) manual fund flow (字段 mainNetInflow / 4 单 净流入 + 净比)
    if _MANUAL_DIR.exists():
        manual_fields = [
            "mainNetInflow", "mainNetInflowRatio",
            "superLargeNetInflow", "superLargeNetInflowRatio",
            "largeNetInflow", "largeNetInflowRatio",
            "mediumNetInflow", "mediumNetInflowRatio",
            "smallNetInflow", "smallNetInflowRatio",
        ]
        files = sorted(
            _MANUAL_DIR.glob("*.json"),
            key=lambda p: p.name,
            reverse=True,
        )[: max(1, days)]
        for f in files:
            data = read_json_file(f, None)
            if not isinstance(data, dict):
                continue
            date_str = _yyyymmdd_to_iso(f.stem)
            if not date_str:
                continue
            point = points_by_date.setdefault(date_str, {"date": date_str})
            _merge_point_fields(point, data, manual_fields, "manual")

    # 4) 给"今天"一个 fallback 点: 拿 fund-flow/latest.json + eltdx latest.json
    #    (仅当 tradingDate = 今天, 且 #1/#2/#3 都没覆盖到).
    today_str = _today_str()
    if today_str not in points_by_date:
        point: dict[str, Any] = {"date": today_str, "source": "eastmoney-latest"}
        for field in _HISTORY_FIELDS:
            point[field] = None

        # akshare latest
        if MARKET_OVERVIEW_LATEST_FILE.exists():
            data = read_json_file(MARKET_OVERVIEW_LATEST_FILE, None)
            if isinstance(data, dict) and data.get("tradingDate") == today_str:
                for field in _HISTORY_FIELDS:
                    v = data.get(field)
                    if v is not None and point.get(field) is None:
                        point[field] = v

        # eltdx latest (兜底 totalAmount / 涨跌家数)
        if _ELTDX_LATEST_FILE.exists():
            data = read_json_file(_ELTDX_LATEST_FILE, None)
            if isinstance(data, dict) and data.get("tradingDate") == today_str:
                for field in (
                    "totalAmount", "totalVolume",
                    "risingCount", "fallingCount", "flatCount",
                    "limitUpCount", "limitDownCount", "stockCount",
                ):
                    v = data.get(field)
                    if v is not None and point.get(field) is None:
                        point[field] = v
                        if point.get("source") == "eastmoney-latest":
                            point["source"] = "eltdx-latest"

        points_by_date[today_str] = point

    # 排序返回 (按日期升序)
    points = list(points_by_date.values())
    points.sort(key=lambda p: p["date"])
    return points
