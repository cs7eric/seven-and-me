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

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from typing import Any, Callable

from backend.config.settings import STOCK_UNIVERSE_DIR

from .stock_universe_service import load_latest, list_sectors_by_category
from .trading_calendar import is_trading_day, previous_trading_day

logger = logging.getLogger(__name__)

# 上一交易日 K-line 快照的本地缓存 (按 trading_day 维度).
# 同一非交易日反复请求时直接读盘, 不再走 eltdx.
QUOTE_CACHE_DIR = STOCK_UNIVERSE_DIR / "_quote_cache"

# 流通股本缓存 (按 trading_day 维度). 流通股本基本每天不变, 缓存即可.
SHARES_CACHE_DIR = STOCK_UNIVERSE_DIR / "_shares_cache"


# ---------------------------------------------------------------------------
# 实时行情 fetcher 抽象 (hotpath)
# ---------------------------------------------------------------------------
# 返回: { "sh600519": {"last_price": 1272.86, "pre_close_price": 1268.0,
#                       "amount": 3984001792.0, "total_hand": 31303, "current_hand": 560,
#                       "open_amount_yuan": 74109950.0, "rise_speed": 0, ...} }

QuoteFetcher = Callable[[list[str]], dict[str, dict[str, Any]]]


def _realtime_quote_fetcher(codes: list[str]) -> dict[str, dict[str, Any]]:
    """实时行情: eltdx list_by_category(6) 4 个 sort_by 角度去重,
    凑出 ~1300 只股票的实时快照 (取不到的全部过滤)."""
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


# ---------------------------------------------------------------------------
# 流通股本 (用于本地算 turnover_rate) — 走 eltdx corporate.finance_batch (0x0010)
# ---------------------------------------------------------------------------
_shares_lock = threading.Lock()
_shares_client = None


def _get_shares_client():
    global _shares_client
    if _shares_client is not None:
        return _shares_client
    with _shares_lock:
        if _shares_client is None:
            import eltdx
            _shares_client = eltdx.TdxClient(pool_size=4, timeout=8.0)
            _shares_client.connect()
    return _shares_client


def _shares_cache_path(target_day: date) -> Any:
    return SHARES_CACHE_DIR / f"{target_day.isoformat()}.json"


def _read_shares_cache(target_day: date) -> dict[str, float]:
    p = _shares_cache_path(target_day)
    if not p.exists():
        return {}
    try:
        with p.open("r", encoding="utf-8") as f:
            blob = json.load(f)
        return {c: float(v) for c, v in (blob.get("shares") or {}).items() if v}
    except Exception:
        return {}


def _write_shares_cache(target_day: date, shares: dict[str, float]) -> None:
    try:
        SHARES_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _shares_cache_path(target_day).with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump({
                "trading_day": target_day.isoformat(),
                "fetched_at": datetime.now().isoformat(),
                "source": "eltdx.corporate.finance_batch(0x0010)",
                "shares": shares,
            }, f, ensure_ascii=False)
        tmp.replace(_shares_cache_path(target_day))
    except Exception as exc:
        logger.warning("shares cache write failed: %s", exc)


def _fetch_circulating_shares(codes: list[str], batch_size: int = 80) -> dict[str, float]:
    """批量拉流通股本, 走 eltdx 0x0010 finance_batch.

    实测 eltdx 0x0010 的 batch 上限 = 80: 80/批 100% 命中, 200/批被服务端截断
    (返回 200 但丢股). 200/批实测缺 2720/5520 = 49% 丢股, 80/批 0% 丢股.

    缓存维度: trading_day. 同一 trading_day 反复请求时直接读盘.
    """
    if not codes:
        return {}
    target_day = date.today() if is_trading_day() else previous_trading_day()
    cached = _read_shares_cache(target_day)
    missing = [c for c in codes if c not in cached]
    if not missing:
        return {c: cached[c] for c in codes if c in cached}

    client = _get_shares_client()
    out: dict[str, float] = dict(cached)
    BATCH = batch_size
    for i in range(0, len(missing), BATCH):
        chunk = missing[i:i + BATCH]
        try:
            res = client.corporate.finance_batch(chunk, fields=["流通股本"])
        except Exception as exc:
            logger.warning("finance_batch failed (batch=%d..%d): %s", i, i + BATCH, exc)
            continue
        if not res:
            continue
        for rec in res:
            fc = rec.get("full_code") or rec.get("code")
            sh = rec.get("流通股本") or rec.get("circulating_shares")
            if fc and sh:
                out[fc] = float(sh)

    if out:
        _write_shares_cache(target_day, out)
    return {c: out[c] for c in codes if c in out}


def _compute_turnover_rate(volume_hand: float, circulating_shares: float) -> float:
    """跟 f10/eltdx_adapter._estimate_turnover_rate 同口径:
       volume(手) * 10000 / circulating_shares(股) * 100% → percent.
    """
    if not volume_hand or not circulating_shares:
        return 0.0
    return round(volume_hand * 10000.0 / circulating_shares, 4)


def _attach_turnover(quotes: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """给所有 quote 加 turnover_rate 字段. 从 finance_batch 拿流通股本本地算.

    缺流通股本的 quote 保留原样, turnover_rate 留 None.
    """
    if not quotes:
        return quotes
    codes = list(quotes.keys())
    shares = _fetch_circulating_shares(codes)
    for c, q in quotes.items():
        sh = shares.get(c)
        vol = float(q.get("total_hand") or 0)
        q["turnover_rate"] = _compute_turnover_rate(vol, sh) if sh else None
        q["circulating_shares"] = sh
    return quotes


# ---------------------------------------------------------------------------
# 非交易日 K-line 回退 (上一交易日 / 再上一交易日 日线收盘价)
# ---------------------------------------------------------------------------
# 共享单 client (eltdx 7709 是单连接 + pool_size 多路长连接),
# 多个 fetcher 进程 / 线程安全靠 client 自带的 pool 多路复用.
_kline_client_lock = threading.Lock()
_kline_client = None


def _get_kline_client():
    global _kline_client
    if _kline_client is not None:
        return _kline_client
    with _kline_client_lock:
        if _kline_client is None:
            import eltdx
            _kline_client = eltdx.TdxClient(pool_size=8, timeout=8.0)
            _kline_client.connect()
    return _kline_client


def _quote_cache_path(target_day: date) -> Any:
    return QUOTE_CACHE_DIR / f"{target_day.isoformat()}.json"


def _read_quote_cache(target_day: date) -> dict[str, dict[str, Any]] | None:
    p = _quote_cache_path(target_day)
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8") as f:
            blob = json.load(f)
    except Exception as exc:
        logger.warning("quote cache read failed (%s): %s", p, exc)
        return None
    return blob.get("quotes") or {}


def _write_quote_cache(target_day: date, quotes: dict[str, dict[str, Any]]) -> None:
    try:
        QUOTE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        blob = {
            "trading_day": target_day.isoformat(),
            "fetched_at": datetime.now().isoformat(),
            "source": "eltdx.bars.get(period=day, count=2)",
            "count": len(quotes),
            "quotes": quotes,
        }
        tmp = _quote_cache_path(target_day).with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(blob, f, ensure_ascii=False)
        tmp.replace(_quote_cache_path(target_day))
    except Exception as exc:
        logger.warning("quote cache write failed: %s", exc)


def _kline_quote_fetcher(codes: list[str]) -> dict[str, dict[str, Any]]:
    """非交易日回退: 用 eltdx 日 K 线 (0x052d) 拉最近 2 根 K 线.

    ``bars[-1]`` = 上一交易日 (target_day) 收盘 → ``last_price``
    ``bars[-2]`` = 再上一交易日收盘 → ``pre_close_price``
    由此算出 ``change_pct`` 与实时分支一致; 成交量/额/换手 留 0 (K 线无此字段).
    """
    target_day = previous_trading_day()
    if not codes:
        return {}

    cached = _read_quote_cache(target_day) or {}
    missing = [c for c in codes if c not in cached]
    if not missing:
        # cache 完整覆盖 codes
        return {c: cached[c] for c in codes if c in cached}

    client = _get_kline_client()
    out: dict[str, dict[str, Any]] = dict(cached)  # 复用已有 cache
    lock = threading.Lock()
    counter = {"done": 0, "hit": 0}
    total = len(missing)

    def fetch_one(code: str) -> None:
        try:
            kline = client.bars.get(code, period="day", count=2)
            bars = kline.bars or []
            if len(bars) < 2:
                return
            last_close = float(bars[-1].close or 0)
            prev_close = float(bars[-2].close or 0)
            if not last_close or not prev_close:
                return
            payload = {
                "last_price": last_close,
                "pre_close_price": prev_close,
                "amount": float(bars[-1].amount or 0),
                "total_hand": float(bars[-1].volume_lots or 0),
                "current_hand": 0.0,
                "open_amount_yuan": 0.0,
                "rise_speed": 0.0,
                "exchange": str(kline.exchange or "").lower(),
            }
            with lock:
                out[code] = payload
                counter["hit"] += 1
        except Exception as exc:
            logger.debug("kline fetch failed for %s: %s", code, exc)
        finally:
            with lock:
                counter["done"] += 1
            if counter["done"] % 500 == 0:
                logger.info("kline fetcher progress: %d/%d (hit=%d)",
                            counter["done"], total, counter["hit"])

    with ThreadPoolExecutor(max_workers=32, thread_name_prefix="kline-fb") as pool:
        futures = [pool.submit(fetch_one, c) for c in missing]
        for fut in as_completed(futures):
            fut.result()

    logger.info("kline fetcher done: %d/%d hit (target_day=%s, missing=%d)",
                counter["hit"], total, target_day.isoformat(), len(missing))
    # 写回: 合并 cache + 新拉的, 下次同 target_day 命中更多
    if counter["hit"] > 0:
        _write_quote_cache(target_day, out)
    return {c: out[c] for c in codes if c in out}


def _default_quote_fetcher(codes: list[str]) -> dict[str, dict[str, Any]]:
    """默认 fetcher: 交易日走实时; 非交易日走 K-line 回退 (上一交易日日 K 收盘价).

    注意: 实时 fetcher 走 list_by_category(6) 拿到的是 eltdx 服务端排序的 ~1300
    只, 其 key 格式跟 universe 的 ``sh600519``/``sz000001``/``bj920211`` 不一定一致
    (eltdx 可能返回纯 6 位数字, 也可能带前缀), 所以判定走不走 fallback 不能
    看实时 dict 是否空, 而要看跟 ``codes`` 的实际交集.
    """
    quotes = _realtime_quote_fetcher(codes)
    hit = {c: quotes[c] for c in codes if c in quotes}
    if hit:
        # 给所有命中的 quote 挂 turnover_rate (从 0x0010 finance_batch 拉流通股本本地算)
        return _attach_turnover(hit)
    if not is_trading_day():
        logger.info("non-trading day, switching to kline fallback (codes=%d, realtime_hit=0)",
                    len(codes))
        return _attach_turnover(_kline_quote_fetcher(codes))
    return hit


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
# kind -> category_raw 映射. eltdx cat=0/2/4 跟 eltdx helpers.stock_topics 里的
# category_raw 字段对齐 (0=行业, 2=概念, 4=风格). 实际 eltdx 服务端 cat=0 数据
# 跟 cat=2 一样是题材+事件+风格的混合, 但文件层我们就按这个三分类驱动 treemap.
KIND_TO_CAT = {"industries": 0, "concepts": 2, "styles": 4}
_KIND_LABELS = {
    "industries": "行业",
    "concepts": "概念",
    "styles": "风格",
}


def _load_sectors_for_kind(kind: str) -> list[dict[str, Any]]:
    """加载单个 kind 的 sector 列表, 过滤掉 stock_count<3 / 无 topic_id 的 sector."""
    cat = KIND_TO_CAT[kind]
    out: list[dict[str, Any]] = []
    for s in list_sectors_by_category(cat):
        sc = s.get("stock_count", 0)
        if sc < 3:
            continue
        if not s.get("topic_id"):
            continue
        codes = s.get("stock_codes") or []
        if len(codes) < 3:
            continue
        out.append(s)
    return out


def _load_name_map() -> dict[str, str]:
    """从 universe + _codes.json 拼一份 code -> name 映射, 优先用 universe."""
    code_to_name: dict[str, str] = {}
    try:
        uni = load_latest()
        for s in (uni or {}).get("stocks", []):
            code = s.get("code")
            name = s.get("name") or ""
            if code and name:
                code_to_name[code] = name
    except Exception as exc:
        logger.warning("name map: universe load failed: %s", exc)
    try:
        codes_file = STOCK_UNIVERSE_DIR / "_codes.json"
        if codes_file.exists():
            blob = json.loads(codes_file.read_text(encoding="utf-8"))
            for c in blob.get("codes") or []:
                fc = c.get("full_code") or c.get("code")
                n = c.get("name") or ""
                if fc and n and fc not in code_to_name:
                    code_to_name[fc] = n
    except Exception as exc:
        logger.warning("name map: _codes.json read failed: %s", exc)
    return code_to_name


def build_market_heatmap(kind: str = "all", top_n: int = 200) -> dict[str, Any]:
    """热力图构建入口. scope 来源: sectors.json 三个分类 (industries/concepts/styles).

    ``kind`` 接受 ``"all"`` / ``"industries"`` / ``"concepts"`` / ``"styles"``.
    ``top_n`` 限制 sector 数 (按 amount 降序截断), 防前端 treemap 渲染压力.

    不再依赖 universe.industry 字段. 板块自身涨跌幅 = sector 内个股 amount
    加权 zdf; 行情拉不到 (hiddenNoQuote) 的股不进 sector 聚合.
    """
    t0 = time.time()

    if kind not in ("all", "industries", "concepts", "styles"):
        return {
            "ok": False,
            "items": [],
            "error": f"unknown kind: {kind!r}, must be all/industries/concepts/styles",
        }

    kinds = list(KIND_TO_CAT.keys()) if kind == "all" else [kind]

    # 1) 加载 sectors, 收集所有唯一 codes
    #    去重: eltdx 同名板块在数字 / X开头 topic_id 两套体系里会建两次, kind 内 name 撞了
    #    的 sector 合并 stock_codes + topic_ids. (kind, name) 是 dedup key, 不跨 kind.
    sector_groups_raw: list[dict[str, Any]] = []
    for k in kinds:
        for s in _load_sectors_for_kind(k):
            codes = list(s.get("stock_codes") or [])
            sector_groups_raw.append({"kind": k, "sector": s, "codes": codes})

    key_index: dict[tuple[str, str], int] = {}
    sector_groups: list[dict[str, Any]] = []
    for g in sector_groups_raw:
        sec = g["sector"]
        name = sec.get("name", "")
        key = (g["kind"], name)
        if key in key_index:
            existing = sector_groups[key_index[key]]
            seen = set(existing["codes"])
            for c in g["codes"]:
                if c not in seen:
                    existing["codes"].append(c)
                    seen.add(c)
            tid = sec.get("topic_id")
            if tid and tid not in existing["topic_ids"]:
                existing["topic_ids"].append(tid)
        else:
            g["topic_ids"] = [sec.get("topic_id")] if sec.get("topic_id") else []
            key_index[key] = len(sector_groups)
            sector_groups.append(g)
    logger.info("scope: %d kinds, %d sectors (dedup from %d), %d unique codes",
                len(kinds), len(sector_groups), len(sector_groups_raw),
                len({c for g in sector_groups for c in g["codes"]}))

    unique_codes: set[str] = set()
    for g in sector_groups:
        unique_codes.update(g["codes"])
    all_codes = sorted(unique_codes)

    # 2) 名字兜底 (从 universe + _codes.json)
    code_to_name = _load_name_map()
    logger.info("name map: %d", len(code_to_name))

    # 3) hotpath 拉行情 (非交易日自动走 K-line fallback)
    quotes = _quote_fetcher(all_codes)
    logger.info("hotpath quote fetcher: %d/%d", len(quotes), len(all_codes))

    # 4) 按 sector 聚合
    items: list[dict[str, Any]] = []
    for g in sector_groups:
        sec = g["sector"]
        sec_quotes: dict[str, dict[str, Any]] = {}
        for c in g["codes"]:
            q = quotes.get(c)
            if q:
                sec_quotes[c] = q
        if not sec_quotes:
            continue

        # 板块自身涨跌幅 = sector 内个股 amount 加权 zdf
        amount_sum = 0.0
        w_change_sum = 0.0
        rising = falling = flat = limit_up = 0
        children: list[dict[str, Any]] = []
        for c, q in sec_quotes.items():
            last = float(q.get("last_price") or 0)
            pre_close = float(q.get("pre_close_price") or 0)
            amount = float(q.get("amount") or 0)
            pct = _safe_pct(last, pre_close)
            amount_sum += amount
            if pct is not None and abs(pct) <= 30:
                w_change_sum += pct * amount
            if pct is None or abs(pct) < 0.0001:
                flat += 1
            elif pct > 0:
                rising += 1
            else:
                falling += 1
            if pct is not None and pct >= 9.9:
                limit_up += 1
            children.append({
                "code": c,
                "name": code_to_name.get(c) or c[-6:],
                "fullCode": c,
                "latestPrice": last or None,
                "changePercent": pct,
                "amount": amount,
                "volume": float(q.get("total_hand") or 0),
                "turnoverRate": q.get("turnover_rate"),
                "circulatingMarketCap": None,
                "totalMarketCap": None,
                "mainNetInflow": None,
                "speed": float(q.get("rise_speed") or 0),
                "limitStreak": 0,
                "boardSealedAmount": None,
                "conceptTags": [],
                "isLimitUp": pct is not None and pct >= 9.9,
                "sectorCode": sec.get("name"),
                "sectorName": sec.get("name"),
                "kind": g["kind"],
            })

        change_pct = round(w_change_sum / amount_sum, 2) if amount_sum > 0 else None
        children.sort(key=lambda x: -(x.get("amount") or 0))
        items.append({
            "name": sec.get("name"),
            "sectorCode": sec.get("name"),
            "kind": g["kind"],
            "kindLabel": _KIND_LABELS.get(g["kind"], g["kind"]),
            "topicId": g.get("topic_ids") or [sec.get("topic_id")],
            "value": amount_sum,
            "changePercent": change_pct,
            "amount": amount_sum,
            "stockCount": len(sec_quotes),
            "risingCount": rising,
            "fallingCount": falling,
            "flatCount": flat,
            "limitUpCount": limit_up,
            "children": children,
        })

    items.sort(key=lambda b: -(b.get("value") or 0))
    items_total = len(items)
    if top_n and len(items) > top_n:
        items = items[:top_n]

    # 统计隐藏数
    visible_codes = {c for it in items for c in (c_["code"] for c_ in it["children"])}
    hidden_no_quote = len([c for c in all_codes if c not in quotes])
    hidden_too_small_sectors = sum(1 for g in sector_groups
                                    if not any(c in quotes for c in g["codes"]))

    elapsed_ms = int((time.time() - t0) * 1000)
    return {
        "ok": True,
        "kind": kind,
        "kinds": [_KIND_LABELS[k] for k in kinds],
        "items": items,
        "totalItems": len(items),
        "itemsTotal": items_total,
        "topN": top_n,
        "totalStocks": len(visible_codes),
        "hiddenStocks": hidden_no_quote,
        "hiddenNoQuote": hidden_no_quote,
        "hiddenEmptySectors": hidden_too_small_sectors,
        "fetchedAt": datetime.now().isoformat(),
        "source": (f"sectors.json({','.join(kinds)}) + "
                   f"{'kline-fallback' if not is_trading_day() else 'list_by_category(6)'} "
                   f"(elapsed {elapsed_ms}ms)"),
    }


def _avg(values: list[float]) -> float | None:
    nums = [v for v in values if v]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 4)
