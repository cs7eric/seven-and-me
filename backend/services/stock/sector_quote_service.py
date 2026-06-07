"""
板块行情 hotpath API (基于 eltdx f10.theme_market).

eltdx theme_market 的 5 个 ReqId:
  200743  某股相关板块 + 涨跌幅 (返回板块列表, 含板块code/名称/涨幅%/涨停数)
  200741  主题区间统计 (近 1/3/5/20/60/1 年 各区间)
  200742  主力资金走势 (近 30 个交易日)
  200744  板块成分股 (按涨幅)
  200745  每日主力控盘比例 (近 30 个交易日)

eltdx 没暴露"按 topic_id 直接查板块行情"的接口, 所有 5 个 API 都需要传 code (种子股).

用法:
  from backend.services.stock import sector_quote_service as sqs
  r = sqs.get_related_sectors("sh600519")
  # [{market, sector_code, sector_name, change_pct, limit_up_count}, ...]
  r = sqs.get_quote_by_topic_id("226")
  # 自动从 sectors.json 找种子股, 拿 5 类数据
"""
from __future__ import annotations

import logging
import threading
from typing import Any

import eltdx

from . import stock_universe_service as sus

logger = logging.getLogger(__name__)

# 共享单 client (eltdx 7709 是单连接 + pool_size 多路长连接)
_client_lock = threading.Lock()
_client: eltdx.TdxClient | None = None


def _get_client() -> eltdx.TdxClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = eltdx.TdxClient(pool_size=4, timeout=8.0)
            _client.connect()
    return _client


# 200741 N001 区间代码 -> 描述
PERIOD_LABELS: dict[str, str] = {
    "0": "近1日",
    "1": "近3日",
    "2": "近5日",
    "3": "近20日",
    "4": "近60日",
    "5": "近1年",
}


# ---------- 字段解析 ----------
def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _parse_table1(resp, kind: str) -> list[dict]:
    """解析 theme_market response 的 table1 字段. eltdx 5 个 ReqId 字段不同."""
    if not getattr(resp, "ok", False):
        return []
    if not resp.tables or len(resp.tables) < 2:
        return []
    t = resp.tables[1]
    if not t.rows:
        return []
    out: list[dict] = []
    for row in t.rows:
        d = dict(row) if isinstance(row, dict) else {}
        if kind == "related":
            # 200743: N001=市场 N002=板块code N003=板块名 N004=涨幅% N005=涨停数
            out.append({
                "market": d.get("N001"),
                "sector_code": d.get("N002"),
                "sector_name": d.get("N003"),
                "change_pct": _to_float(d.get("N004")),
                "limit_up_count": _to_int(d.get("N005")),
            })
        elif kind == "constituents":
            # 200744: N001=市场 N002=code N003=名称 N004=涨幅% N005=现价
            out.append({
                "market": d.get("N001"),
                "code": d.get("N002"),
                "name": d.get("N003"),
                "change_pct": _to_float(d.get("N004")),
                "last_price": _to_float(d.get("N005")),
            })
        elif kind == "main_capital_flow":
            # 200742: N001=行业名 N002=日期 N003=主力净额 N004=大单 N005=中单 N006=小单
            out.append({
                "sector_name": d.get("N001"),
                "date": d.get("N002"),
                "main_net": _to_float(d.get("N003")),
                "large_order_net": _to_float(d.get("N004")),
                "medium_order_net": _to_float(d.get("N005")),
                "small_order_net": _to_float(d.get("N006")),
            })
        elif kind == "main_control":
            # 200745: N001=日期 N002=控盘比例
            out.append({
                "date": d.get("N001"),
                "control_pct": _to_float(d.get("N002")),
            })
        elif kind == "period_stats":
            # 200741: N001=区间代码 0/1/2/3/4/5 N002=值1 N003=值2 N004=0
            n1 = str(d.get("N001") or "")
            out.append({
                "range_code": n1,
                "range_label": PERIOD_LABELS.get(n1, "未知"),
                "value1": _to_float(d.get("N002")),
                "value2": _to_float(d.get("N003")),
                "value3": _to_int(d.get("N004")),
            })
    return out


# ---------- 5 个 API ----------
def get_related_sectors(code: str) -> list[dict]:
    """某股相关板块 + 涨跌幅 (200743).

    返回: ``[{market, sector_code, sector_name, change_pct, limit_up_count}, ...]``
    """
    c = _get_client()
    r = c.f10.theme_market(code, "200743", page=-1, page_size=-1)
    return _parse_table1(r, "related")


def get_period_stats(code: str) -> list[dict]:
    """主题区间统计 (200741).

    返回: ``[{range_code, range_label, value1, value2, value3}, ...]``
    range_label 是 "近1日 / 近3日 / 近5日 / 近20日 / 近60日 / 近1年"
    """
    c = _get_client()
    r = c.f10.theme_market(code, "200741", page=-1, page_size=-1)
    return _parse_table1(r, "period_stats")


def get_main_capital_flow(code: str) -> list[dict]:
    """主力资金走势 (200742). 最近 ~30 个交易日.

    返回: ``[{sector_name, date, main_net, large_order_net, medium_order_net, small_order_net}, ...]``
    """
    c = _get_client()
    r = c.f10.theme_market(code, "200742", page=-1, page_size=-1)
    return _parse_table1(r, "main_capital_flow")


def get_constituents(code: str, sector_code: str | None = None, sector_name: str | None = None) -> list[dict]:
    """板块成分股 (200744, eltdx 当前 server 返 0, 走 fallback).

    eltdx f10.theme_market(req_id=200744) 文档说返"板块成分股", 但 v1.0.2 server
    实际一直返 0 rows. 这里:
      1. 先尝试 eltdx 200744 (有数据就用)
      2. 失败 fallback: 走 sectors.json 拿 stock_codes + qt.gtimg.cn 拉实时行情

    sector_code: 可选, 传了则跨 cat 找 topic_id=sector_code 的板块;
                 没传则用 find_sectors_for 的 cat=2 第一个 concept 板块.
    sector_name: 可选, 用于 industries 板块 (cat=0) 按中文名查.

    返回按 change_pct 降序. None 排最后.
    """
    c = _get_client()
    extra: dict[str, Any] | None = {"sectype": sector_code} if sector_code else None
    try:
        r = c.f10.theme_market(code, "200744", page=-1, page_size=-1, extra=extra)
        parsed = _parse_table1(r, "constituents")
        if parsed:
            return parsed
    except Exception as exc:
        logger.debug("200744 failed: %s", exc)
    # fallback: 找 code 所属板块 + 拉实时行情
    return _fallback_constituents_with_quote(code, sector_code=sector_code, sector_name=sector_name)


def _fallback_constituents_with_quote(seed_code: str, sector_code: str | None = None, sector_name: str | None = None) -> list[dict]:
    """eltdx 200744 失败时: 拿 seed 所属板块 (sectors.json) + qt.gtimg.cn 实时行情.

    sector_code 传了则跨 cat 找 topic_id=sector_code 的板块;
    sector_name 传了则用 cat=0 行业板块按中文名查;
    都没传则用 find_sectors_for 的 cat=2 第一个 concept 板块.
    """
    idx = sus.load_sectors_index()
    if not idx:
        return []
    # 跨 cat 找匹配 sector_code 的板块
    target = None
    if sector_code:
        for cr_str in idx.get("categories", {}):
            for s in sus.list_sectors_by_category(int(cr_str)):
                if str(s.get("topic_id")) == str(sector_code):
                    target = s
                    break
            if target:
                break
    if not target and sector_name:
        for s in sus.list_sectors_by_category(0):
            if s.get("name") == sector_name:
                target = s
                break
    if not target:
        # 用 find_sectors_for 找 stock 所属板块, 再 list_sectors_by_category 拿完整 sector dict (含 stock_codes)
        sectors = sus.find_sectors_for(seed_code)
        if sectors:
            # 优先 cat=2 概念 (更聚焦)
            for s in sectors:
                cr = s.get("category_raw")
                tid = s.get("topic_id")
                if cr == 2 and tid:
                    for full in sus.list_sectors_by_category(2):
                        if str(full.get("topic_id")) == str(tid):
                            target = full
                            break
                    if target:
                        break
            if not target:
                # 然后 cat=0 行业
                for s in sectors:
                    cr = s.get("category_raw")
                    tid = s.get("topic_id")
                    if cr == 0:
                        if tid:
                            for full in sus.list_sectors_by_category(0):
                                if str(full.get("topic_id")) == str(tid):
                                    target = full
                                    break
                        else:
                            for full in sus.list_sectors_by_category(0):
                                if full.get("name") == s.get("name"):
                                    target = full
                                    break
                        if target:
                            break
            if not target and sectors:
                # 兜底: 用 list_sectors_by_category 直接找含 seed_code 的
                for cr_int in [2, 0, 4]:
                    for full in sus.list_sectors_by_category(cr_int):
                        if seed_code in (full.get("stock_codes") or []):
                            target = full
                            break
                        if len(target if target else []) > 50:
                            break
                    if target:
                        break
    if not target:
        return []
    # target 是 list_sectors_by_category 返回的 dict, 已有 stock_codes 字段
    codes = target.get("stock_codes") or []
    if not codes:
        return []
    quotes = _qt_snapshots(codes)
    out: list[dict] = []
    for c in codes:
        q = quotes.get(c, {})
        out.append({
            "market": c[:2],
            "code": c,
            "name": q.get("name", c[-6:]),
            "change_pct": q.get("change_pct"),
            "last_price": q.get("last_price"),
        })
    # 按 change_pct 降序 (None 排最后)
    out.sort(key=lambda x: (x.get("change_pct") is None, -(x.get("change_pct") or 0)))
    return out


def _qt_snapshots(codes: list[str]) -> dict[str, dict[str, Any]]:
    """腾讯 qt.gtimg.cn 批量快照. 500/0.22s."""
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    opener.addheaders = [
        ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"),
        ("Referer", "https://gu.qq.com/"),
    ]
    out: dict[str, dict[str, Any]] = {}
    for i in range(0, len(codes), 500):
        batch = codes[i:i + 500]
        url = "https://qt.gtimg.cn/q=" + ",".join(batch)
        try:
            resp = opener.open(url, timeout=10)
            body = resp.read().decode("gbk", errors="ignore")
        except Exception as exc:
            logger.debug("qt batch %d failed: %s", i // 500, exc)
            continue
        for line in body.strip().split(";"):
            if "~" not in line:
                continue
            parts = line.split("~")
            if len(parts) < 5:
                continue
            # parts[0] = 'v_sh600519="1',  解析 market
            market_marker = parts[0].strip()
            true_code = parts[2].strip() if len(parts) > 2 else ""
            if not true_code:
                continue
            if market_marker.startswith("v_sh"):
                full_code = "sh" + true_code
            elif market_marker.startswith("v_sz"):
                full_code = "sz" + true_code
            elif market_marker.startswith("v_bj"):
                full_code = "bj" + true_code
            else:
                full_code = true_code
            try:
                last = float(parts[3])
                pre_close = float(parts[4])
            except (TypeError, ValueError):
                last = 0
                pre_close = 0
            pct = (last - pre_close) / pre_close * 100.0 if pre_close else None
            out[full_code] = {
                "name": parts[1].strip() if len(parts) > 1 else "",
                "last_price": last if last else None,
                "pre_close_price": pre_close if pre_close else None,
                "change_pct": pct,
            }
    return out


def get_main_control(code: str) -> list[dict]:
    """每日主力控盘比例 (200745). 最近 ~30 个交易日.

    返回: ``[{date, control_pct}, ...]``
    """
    c = _get_client()
    r = c.f10.theme_market(code, "200745", page=-1, page_size=-1)
    return _parse_table1(r, "main_control")


# ---------- 便捷: 通过 topic_id 自动找种子股 ----------
def _seed_code_for_topic(topic_id: str) -> str | None:
    """从 sectors.json 找 topic_id 的某只成分股作为种子股."""
    idx = sus.load_sectors_index()
    if not idx:
        return None
    for cr_str in idx.get("categories", {}):
        for s in sus.list_sectors_by_category(int(cr_str)):
            if str(s.get("topic_id")) == str(topic_id):
                codes = s.get("stock_codes") or []
                if codes:
                    return codes[0]
    return None


def get_quote_by_topic_id(topic_id: str, *, which: str = "all") -> dict[str, Any]:
    """通过 topic_id 拿板块行情 (自动从 sectors.json 找种子股).

    which:
      - "all"          : 拿 5 类 (默认)
      - "related"      : 200743 相关板块
      - "stats"        : 200741 区间统计
      - "flow"         : 200742 主力资金
      - "constituents" : 200744 板块成分股
      - "control"      : 200745 主力控盘
    """
    seed = _seed_code_for_topic(topic_id)
    if not seed:
        return {"error": "no seed for topic_id={}".format(topic_id), "topic_id": topic_id}
    out: dict[str, Any] = {"topic_id": topic_id, "seed_code": seed}
    if which in ("all", "related"):
        out["related_sectors"] = get_related_sectors(seed)
    if which in ("all", "stats"):
        out["period_stats"] = get_period_stats(seed)
    if which in ("all", "flow"):
        out["main_capital_flow"] = get_main_capital_flow(seed)
    if which in ("all", "constituents"):
        out["constituents"] = get_constituents(seed)
    if which in ("all", "control"):
        out["main_control"] = get_main_control(seed)
    return out
