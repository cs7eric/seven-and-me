"""qt.gtimg.cn 个股资金流代理 (走主接口 88 字段, 解析 part[7]/part[8]).

字段口径 (qt.gtimg.cn/q=sh600519 返 v_sh600519, 88 字段 ~ 分隔):

  3  当前价
  4  昨收
  5  今开
  6  成交量(手)
  7  外盘(手)        = 主动买入
  8  内盘(手)        = 主动卖出
  31 涨跌
  32 涨跌幅%
  33 最高
  34 最低
  36 成交量(手)
  37 成交额(万)
  38 换手率%
  39 市盈率
  43 振幅%
  44 流通市值(亿)
  45 总市值(亿)
  46 市净率

注意:
  - qt 是 GBK 编码, 名字可能带空格 (e.g. "五 粮 液")
  - 单次请求可批量 (q=sh600519,sh601398,sz000858), ~150ms 内全返
  - qt 对出口 IP 不像同花顺那么敏感
  - **无"主力/大单/中单/小单"分单维度**, 只有"外盘/内盘" (主动买卖总量)
  - "ff_" 个股资金流接口在 2026 已下架 (返 v_pv_none_match="1")
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from backend.config.settings import STOCK_UNIVERSE_DIR

logger = logging.getLogger(__name__)

QT_FUND_DIR: Final[Path] = STOCK_UNIVERSE_DIR / "qt_fund_flow"
QT_FUND_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = [
    ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    ("Referer", "https://gu.qq.com/"),
]
URL_BASE = "https://qt.gtimg.cn/q="

_opener: urllib.request.OpenerDirector | None = None
_opener_lock = threading.Lock()


def _get_opener() -> urllib.request.OpenerDirector:
    global _opener
    if _opener is not None:
        return _opener
    with _opener_lock:
        if _opener is None:
            _opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            _opener.addheaders = HEADERS
    return _opener


def _to_float(s: str | None) -> float | None:
    if s is None: return None
    try:
        v = float(s); return v if v == v else None
    except (TypeError, ValueError):
        return None


def _parse_qt_line(key: str, value: str) -> dict[str, Any] | None:
    """解析 v_<key>="..." 一行, 返字段 dict (主接口 88 字段)."""
    parts = value.strip('"').split("~")
    if len(parts) < 50:
        return None
    return {
        "code":     parts[2],
        "name":     parts[1].strip() or None,
        "lastPrice":    _to_float(parts[3]),
        "preClose":     _to_float(parts[4]),
        "open":         _to_float(parts[5]),
        "volumeLots":   _to_float(parts[6]),     # 成交量(手)
        "outerDisc":    _to_float(parts[7]),     # 外盘 (主动买入, 手)
        "insideDish":   _to_float(parts[8]),     # 内盘 (主动卖出, 手)
        "change":       _to_float(parts[31]),
        "changePct":    _to_float(parts[32]),
        "high":         _to_float(parts[33]),
        "low":          _to_float(parts[34]),
        "amountWan":    _to_float(parts[37]),    # 成交额(万)
        "turnoverRate": _to_float(parts[38]),
        "pe":           _to_float(parts[39]),
        "amplitude":    _to_float(parts[43]),
        "floatMarketCapYi": _to_float(parts[44]),
        "totalMarketCapYi": _to_float(parts[45]),
        "pb":           _to_float(parts[46]),
        "fetchedAt":    datetime.now().isoformat(timespec="seconds"),
    }


def _parse_spk_line(value: str) -> dict[str, Any] | None:
    """解析 s_pk<key> (4 字段百分比, 盘口买卖大单小单占比).

    parts: 买盘大单, 买盘小单, 卖盘大单, 卖盘小单 (小数百分比 0~1)
    """
    parts = value.strip('"').split("~")
    if len(parts) < 4:
        return None
    return {
        "buyBigRatio":    _to_float(parts[0]),  # 买盘大单占比
        "buySmallRatio":  _to_float(parts[1]),  # 买盘小单占比
        "sellBigRatio":   _to_float(parts[2]),  # 卖盘大单占比
        "sellSmallRatio": _to_float(parts[3]),  # 卖盘小单占比
    }


def _disk_path(code: str) -> Path:
    return QT_FUND_DIR / f"{code}.json"


# =============================================================================
# 顶层
# =============================================================================
def fetch_qt_fund_flow(code: str, *, refresh: bool = False) -> dict[str, Any] | None:
    """单只个股主接口 (88 字段) + 盘口占比 (s_pk).

    code 形如 'sh600519' 或 'sz000858' 或 'bj830799'.
    """
    code = (code or "").strip().lower()
    if not code:
        return None
    p = _disk_path(code)
    if not refresh and p.exists():
        try:
            blob = json.loads(p.read_text(encoding="utf-8"))
            return blob
        except Exception:
            pass

    # 主接口 + 盘口占比, 批量请求
    url = f"{URL_BASE}{code},{ 's_pk' + code}"
    try:
        t0 = time.time()
        resp = _get_opener().open(url, timeout=8)
        body = resp.read().decode("gb18030", errors="ignore")
        elapsed = round((time.time() - t0) * 1000)
    except Exception as exc:
        logger.warning("qt fund flow %s failed: %s", code, exc)
        return None

    # 找主接口行
    main_row: dict[str, Any] | None = None
    spk_row:  dict[str, Any] | None = None
    for line in body.splitlines():
        if "=" not in line: continue
        k, v = line.split("=", 1)
        if k.strip() == f"v_{code}":
            main_row = _parse_qt_line(k.strip(), v)
        elif k.strip() == f"v_s_pk{code}":
            spk_row = _parse_spk_line(v)

    if not main_row:
        return None

    # 主动净流入 (手) = 外盘 - 内盘
    outer = main_row.get("outerDisc") or 0.0
    inner = main_row.get("insideDish") or 0.0
    active_net_lots = outer - inner
    total_lots = main_row.get("volumeLots") or 0.0
    active_buy_ratio  = outer / total_lots if total_lots else None
    active_sell_ratio = inner / total_lots if total_lots else None

    out: dict[str, Any] = {
        **main_row,
        "activeNetLots": active_net_lots,         # 主动净流入 (手)
        "activeNetAmountWan": (active_net_lots * (main_row.get("lastPrice") or 0)) / 10000,  # 折算 (万)
        "activeBuyRatio":  active_buy_ratio,
        "activeSellRatio": active_sell_ratio,
        "disk": {
            "buyBigRatio":    spk_row.get("buyBigRatio")    if spk_row else None,
            "buySmallRatio":  spk_row.get("buySmallRatio")  if spk_row else None,
            "sellBigRatio":   spk_row.get("sellBigRatio")   if spk_row else None,
            "sellSmallRatio": spk_row.get("sellSmallRatio") if spk_row else None,
        },
        "source": "qt.gtimg.cn main + s_pk",
        "elapsedMs": elapsed,
    }
    try:
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("write qt fund cache %s failed: %s", code, exc)
    return out


def fetch_qt_fund_flow_batch(codes: list[str], *, refresh: bool = False) -> dict[str, dict[str, Any]]:
    """多只批量 (qt 主接口支持 q=a,b,c 一次 200ms)."""
    codes = [c.strip().lower() for c in codes if c]
    if not codes:
        return {}
    # 主接口批量
    main_codes = codes
    spk_codes  = [f"s_pk{c}" for c in codes]
    url = URL_BASE + ",".join(main_codes + spk_codes)
    out: dict[str, dict[str, Any]] = {}
    try:
        t0 = time.time()
        resp = _get_opener().open(url, timeout=10)
        body = resp.read().decode("gb18030", errors="ignore")
        elapsed = round((time.time() - t0) * 1000)
    except Exception as exc:
        logger.warning("qt batch fund flow failed: %s", exc)
        return out

    spk_by_code = {}
    for line in body.splitlines():
        if "=" not in line: continue
        k, v = line.split("=", 1)
        ks = k.strip()
        if ks.startswith("v_s_pk"):
            sc = ks[len("v_s_pk"):]
            spk_by_code[sc] = _parse_spk_line(v)
        elif ks.startswith("v_") and not ks.startswith("v_s_"):
            sc = ks[2:]
            parsed = _parse_qt_line(ks, v)
            if parsed:
                outer = parsed.get("outerDisc") or 0.0
                inner = parsed.get("insideDish") or 0.0
                total = parsed.get("volumeLots") or 0.0
                parsed["activeNetLots"] = outer - inner
                parsed["activeNetAmountWan"] = (outer - inner) * (parsed.get("lastPrice") or 0) / 10000
                parsed["activeBuyRatio"] = outer / total if total else None
                parsed["activeSellRatio"] = inner / total if total else None
                parsed["disk"] = spk_by_code.get(sc, {})
                parsed["elapsedMs"] = elapsed
                out[sc] = parsed
    # 落盘
    for sc, blob in out.items():
        p = _disk_path(sc)
        try:
            p.write_text(json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    return out
