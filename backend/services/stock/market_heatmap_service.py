"""
市场热力图（同花顺式）数据源.

行业归一 (code → industry / topic) 走 :mod:`backend.services.stock.stock_universe_service` 的
每日持久化 JSON (拉一次后当天 ms 级响应).

行情 (change_pct / amount / volume) 走 hotpath, 默认通过
:func:`fetch_realtime_quotes` 拿 —— 默认实现是用 eltdx ``list_by_category(6)``
按 sort_by=涨幅 / 振幅 4 个角度取, 已经能稳定给到 ~1300 只股票
的实时行情 (日均实时变动).

如果后续接其它行情 API (东方财富 push2 / 同花顺 / 雪球), 改
``fetch_realtime_quotes`` 的实现即可, 上层 treemap 渲染逻辑不动.

返回结构:
  {
    "ok": True,
    "items": [<sector>, <sector>, ...],
    "totalStocks": <可见总股数>,
    "hiddenStocks": <被隐藏的 < 3 只的散行业 + 拉不到行情的代码>,
    "fetchedAt": "...",
    "source": "...",
    "tradingDay": "2026-06-06"
  }
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Callable

from .stock_universe_service import load_latest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 实时行情 fetcher 抽象 (hotpath)
# ---------------------------------------------------------------------------
# 返回: { "sh600519": {"last_price": 1272.86, "pre_close_price": 1268.0,
#                       "amount": 3984001792.0, "total_hand": 31303, "current_hand": 560,
#                       "open_amount_yuan": 74109950.0, "rise_speed": 0, ...} }

QuoteFetcher = Callable[[list[str]], dict[str, dict[str, Any]]]


def _default_quote_fetcher(codes: list[str]) -> dict[str, dict[str, Any]]:
    """默认 fetcher: eltdx list_by_category(6) 4 个 sort_by 角度去重,
    凑出 ~1300 只股票的实时快照 (取不到的全部过滤).

    需要换行情源时, 把这个函数替换掉即可.
    """
    try:
        from .f10.service import get_fundamentals_service
    except Exception:
        return {}

    svc = get_fundamentals_service()
    out: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    jobs = [
        {"sort_by": "涨幅", "ascending": False},
        {"sort_by": "涨幅", "ascending": True},
        {"sort_by": "振幅", "ascending": False},
        {"sort_by": "振幅", "ascending": True},
    ]
    for job in jobs:
        start = 0
        for _ in range(8):
            try:
                payload = svc.list_sectors_market(
                    category=6, sort_by=job["sort_by"], ascending=job["ascending"],
                    start=start, count=80,
                )
            except Exception as exc:
                logger.warning("list_sectors_market failed: %s", exc)
                break
            items = payload.get("items") or []
            if not items:
                break
            for raw in items:
                code = str(raw.get("code") or "").strip()
                if not code or code in seen:
                    continue
                seen.add(code)
                last = float(raw.get("last_price") or 0)
                pre_close = float(raw.get("pre_close_price") or 0)
                out[code] = {
                    "last_price": last,
                    "pre_close_price": pre_close,
                    "amount": float(raw.get("amount") or 0),
                    "total_hand": float(raw.get("total_hand") or 0),
                    "current_hand": float(raw.get("current_hand") or 0),
                    "open_amount_yuan": float(raw.get("open_amount") or 0),
                    "rise_speed": float(raw.get("rise_speed") or 0),
                    "exchange": str(raw.get("exchange") or "").lower(),
                }
            if len(items) < 80:
                break
            start += 80
    return out


_quote_fetcher: QuoteFetcher = _default_quote_fetcher


def set_quote_fetcher(fetcher: QuoteFetcher) -> None:
    """给后端 hotpath 切行情源 (push2.eastmoney / ths / xueqiu)."""
    global _quote_fetcher
    _quote_fetcher = fetcher


def _safe_pct(last: float, pre_close: float) -> float | None:
    if not last or not pre_close:
        return None
    return (last - pre_close) / pre_close * 100.0


# ---------------------------------------------------------------------------
# 构建热力图
# ---------------------------------------------------------------------------


def build_market_heatmap() -> dict[str, Any]:
    t0 = time.time()

    universe = load_latest()
    if not universe:
        return {
            "ok": False,
            "items": [],
            "totalStocks": 0,
            "hiddenStocks": 0,
            "fetchedAt": None,
            "tradingDay": None,
            "source": "stock-universe (no data, run refresh_stock_universe)",
            "error": "no stock universe data, please run refresh_stock_universe.py first",
        }

    # 1) 行业归一 (来自持久化 universe)
    code_to_industry: dict[str, str] = {}
    code_to_topics: dict[str, list[dict[str, Any]]] = {}
    for s in universe.get("stocks", []):
        code = s.get("code")
        if not code:
            continue
        ind = s.get("industry") or ""
        if ind:
            code_to_industry[code] = ind
        code_to_topics[code] = s.get("topics") or []

    # 2) hotpath 拉行情 (f10 list_by_category 4 角度, ~1300 只)
    all_codes = list(code_to_industry.keys())
    quotes = _quote_fetcher(all_codes)
    logger.info("hotpath quote fetcher returned %d quotes (out of %d codes)", len(quotes), len(all_codes))

    # 3) 按行业聚
    sectors: dict[str, dict[str, Any]] = {}
    hidden_no_quote = 0
    for code in all_codes:
        q = quotes.get(code)
        if not q:
            hidden_no_quote += 1
            continue
        industry = code_to_industry[code]
        last = float(q.get("last_price") or 0)
        pre_close = float(q.get("pre_close_price") or 0)
        amount = float(q.get("amount") or 0)
        open_amount = float(q.get("open_amount_yuan") or 0)
        rise_speed = float(q.get("rise_speed") or 0)
        pct = _safe_pct(last, pre_close)
        turnover = float(q.get("current_hand") or 0) / max(float(q.get("total_hand") or 0), 1) * 100

        bucket = sectors.setdefault(industry, {
            "name": industry,
            "sectorCode": industry,
            "kind": "industry",
            "value": 0.0,
            "changePercentSum": 0.0,
            "changePercentCount": 0,
            "changePercent": None,
            "amount": 0.0,
            "circulatingMarketCap": 0.0,
            "stockCount": 0,
            "risingCount": 0,
            "fallingCount": 0,
            "flatCount": 0,
            "mainNetInflow": 0.0,
            "turnoverRateAvg": None,
            "speedAvg": None,
            "limitUpCount": 0,
            "conceptTags": set(),
            "children": [],
            "_turnover": [],
            "_speed": [],
        })
        bucket["stockCount"] += 1
        bucket["amount"] += amount
        bucket["circulatingMarketCap"] += open_amount
        bucket["mainNetInflow"] += open_amount
        bucket["value"] += amount
        if pct is not None and abs(pct) <= 30:
            bucket["changePercentSum"] += pct
            bucket["changePercentCount"] += 1
        bucket["_turnover"].append(turnover)
        bucket["_speed"].append(rise_speed)
        if pct is None or abs(pct) < 0.0001:
            bucket["flatCount"] += 1
        elif pct > 0:
            bucket["risingCount"] += 1
        else:
            bucket["fallingCount"] += 1
        if pct is not None and pct >= 9.9:
            bucket["limitUpCount"] += 1
        for t in code_to_topics.get(code, []):
            tname = t.get("topic_name")
            if tname:
                bucket["conceptTags"].add(tname)
        bucket["children"].append({
            "code": code,
            "name": code[-6:],  # 没名字, code 6 位兜底
            "fullCode": code,
            "latestPrice": last or None,
            "changePercent": pct,
            "amount": amount,
            "volume": float(q.get("total_hand") or 0),
            "turnoverRate": turnover,
            "circulatingMarketCap": open_amount,
            "totalMarketCap": open_amount,
            "mainNetInflow": open_amount,
            "speed": rise_speed,
            "limitStreak": 0,
            "boardSealedAmount": None,
            "conceptTags": [t.get("topic_name") for t in code_to_topics.get(code, []) if t.get("topic_name")][:5],
            "isLimitUp": pct is not None and pct >= 9.9,
            "sectorCode": industry,
            "sectorName": industry,
        })

    # 4) 整理
    items: list[dict[str, Any]] = []
    hidden_too_small = 0
    for bucket in sectors.values():
        if bucket["stockCount"] == 0:
            continue
        if bucket["stockCount"] < 3:
            hidden_too_small += bucket["stockCount"]
            continue
        bucket["children"].sort(key=lambda c: -(c.get("amount") or 0))
        bucket["turnoverRateAvg"] = _avg(bucket.pop("_turnover"))
        bucket["speedAvg"] = _avg(bucket.pop("_speed"))
        bucket["changePercent"] = (
            round(bucket["changePercentSum"] / bucket["changePercentCount"], 2)
            if bucket["changePercentCount"] > 0
            else None
        )
        bucket["mainNetInflow"] = round(bucket["mainNetInflow"], 2)
        bucket["conceptTags"] = sorted(bucket["conceptTags"])[:8]
        bucket.pop("changePercentSum", None)
        bucket.pop("changePercentCount", None)
        items.append(bucket)

    items.sort(key=lambda b: -(b.get("value") or 0))

    total_visible = sum(len(s["children"]) for s in items)
    elapsed_ms = int((time.time() - t0) * 1000)
    return {
        "ok": True,
        "items": items,
        "totalStocks": total_visible,
        "hiddenStocks": hidden_too_small + hidden_no_quote,
        "hiddenNoQuote": hidden_no_quote,
        "hiddenSmallSectors": hidden_too_small,
        "fetchedAt": datetime.now().isoformat(),
        "tradingDay": universe.get("trading_day"),
        "source": f"universe={universe.get('trading_day')} + eltdx.list_by_category(6) (elapsed {elapsed_ms}ms)",
    }


def _avg(values: list[float]) -> float | None:
    nums = [v for v in values if v]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 4)
