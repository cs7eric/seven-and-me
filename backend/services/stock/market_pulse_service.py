"""Stock Overview · Market Pulse 后端服务.

三个模块:
  1. 强势板块 (Strong Sectors)      - TDX 56 行业指数实时, 按 change_pct 排序
  2. 行业主力净流入 (Capital Flow)   - eltdx 200742 (复用 sector_quote_service)
  3. 行业轮动 (Industry Rotation)   - 每天收盘后把 TDX 56 行业指数当日 Top N 落盘,
                                     后续直接读 reference/stock-universe/market_pulse/rotation/<date>.json
"""
from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from backend.config.settings import STOCK_UNIVERSE_DIR

from .f10.tdx_industry_codes import TDX_INDUSTRY_56
from .f10.tdx_industry_service import build_industry_market_payload
from .sector_quote_service import get_main_capital_flow

logger = logging.getLogger(__name__)

# 行业资金流数据源: akshare (同花顺) 拿 90 个行业的真实流入/流出/净额 + 领涨股.
# 老 200742 个股代理流程暂留, 但 build_capital_flow 不再走它, 改走 akshare.
try:
    import akshare as ak  # noqa: F401
    _AKSHARE_AVAILABLE = True
except ImportError:
    _AKSHARE_AVAILABLE = False
    logger.warning("akshare not installed; build_capital_flow will fall back to 200742 seed pool")

# 持久化目录: 每个交易日一份快照
ROTATION_DIR: Final[Path] = STOCK_UNIVERSE_DIR / "market_pulse" / "rotation"
ROTATION_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_TOP_N: Final[int] = 10
DEFAULT_FLOW_DAYS: Final[int] = 30


# ---------------------------------------------------------------------------
# 1. 强势板块 - akshare (同花顺) 90 行业真实当日涨跌幅 (含真实资金流)
# ---------------------------------------------------------------------------
def _fetch_akshare_industry_spot() -> list[dict[str, Any]] | None:
    """ak.stock_fund_flow_industry() 90 行, 同时含涨跌幅 / 流入 / 流出 / 净额 / 领涨股.

    字段口径跟 build_capital_flow 复用同一接口, 这里转成"行业实时行情"语义.
    """
    return _fetch_one_flow_akshare()


def build_strong_sectors(top_n: int = DEFAULT_TOP_N) -> dict[str, Any]:
    """akshare 90 行业当日实时涨跌幅榜.

    替代之前 TDX 56 行业指数口径. 字段: name, changePct, amount (本行业指数成交额不可得,
    暂用 mainNet 替代做排序面积), leadingStock, leadingChangePct, stockCount.

    TDX 56 行业指数接口 / 数据 / heatmap industries 屏全部保留, 仅行情页换源.
    """
    rows = _fetch_akshare_industry_spot()
    if not rows:
        return {
            "ok": False,
            "kind": "akshare.industry",
            "label": "行业",
            "top": [],
            "bottom": [],
            "count": 0,
            "topN": top_n,
            "fetchedAt": datetime.now().isoformat(timespec="seconds"),
            "source": "akshare.stock_fund_flow_industry (failed)",
            "error": "akshare returned empty",
        }

    # 90 行, 按 changePct 排序
    rows_with_chg = [r for r in rows if r.get("changePct") is not None]
    rows_with_chg.sort(key=lambda r: -(r.get("changePct") or 0))

    top = rows_with_chg[:top_n]
    bottom = list(reversed(rows_with_chg[-min(top_n, len(rows_with_chg)):]))

    # amount 字段用 mainNet 替代, 给前端 treemap 排序/面积用. 单位: 亿.
    for r in top + bottom:
        r["amount"] = (r.get("mainNet") or 0) * 1e8  # 转元, 跟 tdx 口径对齐
        r["changePercent"] = r.get("changePct")

    return {
        "ok": True,
        "kind": "akshare.industry",
        "label": "行业",
        "top": top,
        "bottom": bottom,
        "count": len(rows_with_chg),
        "topN": top_n,
        "fetchedAt": datetime.now().isoformat(timespec="seconds"),
        "source": "akshare.stock_fund_flow_industry (10jqka)",
    }


# ---------------------------------------------------------------------------
# 2. 行业主力净流入 - akshare (同花顺) 90 行业真实板块资金流
# ---------------------------------------------------------------------------
def _fetch_one_flow_akshare() -> list[dict[str, Any]] | None:
    """调 ``ak.stock_fund_flow_industry()`` 拿 90 行业流入/流出/净额/领涨股.

    返回 list of dict, 每项字段:
      行业, 行业指数, 行业-涨跌幅, 流入资金, 流出资金, 净额 (单位: 亿),
      公司家数, 领涨股, 领涨股-涨跌幅, 当前价
    """
    if not _AKSHARE_AVAILABLE:
        return None
    try:
        import akshare as ak
        df = ak.stock_fund_flow_industry()
    except Exception as exc:
        logger.warning("ak.stock_fund_flow_industry failed: %s", exc)
        return None
    if df is None or df.empty:
        return None

    out: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        try:
            out.append({
                "name":        str(row.get("行业") or "").strip(),
                "index":       _to_float(row.get("行业指数")),
                "changePct":   _to_float(row.get("行业-涨跌幅")),
                "inflow":      _to_float(row.get("流入资金")) or 0.0,  # 亿
                "outflow":     _to_float(row.get("流出资金")) or 0.0,  # 亿
                "mainNet":     _to_float(row.get("净额"))       or 0.0,  # 亿
                "stockCount":  int(row.get("公司家数") or 0),
                "leadingStock": str(row.get("领涨股") or "").strip() or None,
                "leadingChangePct": _to_float(row.get("领涨股-涨跌幅")),
                "leadingPrice": _to_float(row.get("当前价")),
            })
        except Exception as exc:
            logger.debug("flow row parse failed: %s", exc)
            continue
    return out


def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def build_capital_flow(top_n: int = 20) -> dict[str, Any]:
    """90 行业 (akshare 同花顺) 真实板块资金流: 流入/流出/净额 + 领涨股.

    替代旧的 eltdx 200742 个股代理口径. 单位: 亿.

    Returns:
      {
        ok, kind, inflow, outflow, inflowCount, outflowCount,
        totalIndustries, elapsedMs, fetchedAt, source
      }

      每行字段:
        name, changePct, mainNet (亿), inflow (亿), outflow (亿),
        stockCount, leadingStock, leadingChangePct, leadingPrice
    """
    t0 = datetime.now()
    rows = _fetch_one_flow_akshare()

    if not rows:
        # akshare 不可用, 走老的 200742 seed pool fallback
        logger.warning("akshare flow failed, falling back to 200742 seed pool")
        return _build_capital_flow_legacy(top_n=top_n)

    inflow  = sorted([r for r in rows if r["mainNet"]  > 0], key=lambda r: -r["mainNet"])
    outflow = sorted([r for r in rows if r["mainNet"] <= 0], key=lambda r:  r["mainNet"])

    elapsed_ms = int((datetime.now() - t0).total_seconds() * 1000)

    # 顺手落 duckdb (字段级 INSERT OR REPLACE, 失败不影响主流程)
    try:
        from backend.repositories.market.market_pulse_sector_repo import upsert_sector_spot
        upsert_sector_spot(rows, trade_date=date.today(),
                           source="akshare.stock_fund_flow_industry")
    except Exception as exc:
        logger.debug("upsert_sector_spot to duckdb failed (non-fatal): %s", exc)

    return {
        "ok": True,
        "kind": "akshare.industry",
        "inflow": inflow[:top_n],
        "outflow": outflow[:top_n],
        "inflowCount": len(inflow),
        "outflowCount": len(outflow),
        "count": len(rows),
        "totalIndustries": len(rows),
        "elapsedMs": elapsed_ms,
        "fetchedAt": datetime.now().isoformat(timespec="seconds"),
        "source": "akshare.stock_fund_flow_industry (10jqka)",
        "unit": "亿",
    }


def _build_capital_flow_legacy(days: int = DEFAULT_FLOW_DAYS, top_n: int = 20) -> dict[str, Any]:
    """老 200742 seed pool fallback. 不动, 留作 akshare 不可用时退路."""
    t0 = datetime.now()
    results: list[dict[str, Any]] = []
    items = list(TDX_INDUSTRY_56.items())

    with ThreadPoolExecutor(max_workers=24, thread_name_prefix="flow-200742") as pool:
        futures = {pool.submit(_fetch_one_flow_legacy, c6, name, days): c6 for c6, name in items}
        for fut, c6 in futures.items():
            try:
                row = fut.result(timeout=30)
            except Exception as exc:
                logger.warning("flow %s failed: %s", c6, exc)
                continue
            if row:
                results.append(row)

    inflow  = sorted([r for r in results if r["mainNet"]  > 0], key=lambda r: -r["mainNet"])
    outflow = sorted([r for r in results if r["mainNet"] <= 0], key=lambda r:  r["mainNet"])

    elapsed_ms = int((datetime.now() - t0).total_seconds() * 1000)
    return {
        "ok": True,
        "kind": "eltdx.200742",
        "inflow": inflow[:top_n],
        "outflow": outflow[:top_n],
        "inflowCount": len(inflow),
        "outflowCount": len(outflow),
        "count": len(results),
        "totalIndustries": len(items),
        "elapsedMs": elapsed_ms,
        "fetchedAt": datetime.now().isoformat(timespec="seconds"),
        "source": "eltdx.f10.theme_market(200742, seed pool)",
        "unit": "元",
    }


def _fetch_one_flow_legacy(code6: str, name: str, days: int) -> dict[str, Any] | None:
    """老 200742 seed pool 单行业实现. 留 fallback. 单位: 元."""
    from .f10.tdx_industry_seeds import seed_for
    for seed in seed_for(code6):
        try:
            rows = get_main_capital_flow(seed) or []
        except Exception as exc:
            logger.debug("200742 failed for %s / seed %s: %s", code6, seed, exc)
            continue
        if not rows:
            continue
        rows_sorted = sorted(rows, key=lambda r: r.get("date") or "", reverse=True)[:days]
        latest = rows_sorted[0] if rows_sorted else None
        if not latest:
            continue
        streak = 0
        for r in rows_sorted:
            v = r.get("main_net")
            if v is None:
                break
            if v > 0 and streak >= 0:
                streak += 1
            elif v < 0 and streak <= 0:
                streak -= 1
            else:
                break
        return {
            "code6": code6,
            "name": name,
            "seed": seed,
            "date": latest.get("date"),
            "mainNet": float(latest.get("main_net") or 0),
            "largeNet": float(latest.get("large_order_net") or 0),
            "mediumNet": float(latest.get("medium_order_net") or 0),
            "smallNet": float(latest.get("small_order_net") or 0),
            "consecutiveDays": streak,
        }
    return None


# ---------------------------------------------------------------------------
# 3. 行业轮动 - 每天收盘落盘, 后续读盘
# ---------------------------------------------------------------------------
def _rotation_path(target_day: date) -> Path:
    return ROTATION_DIR / f"{target_day.isoformat()}.json"


def _write_rotation(target_day: date, payload: dict[str, Any]) -> Path:
    p = _rotation_path(target_day)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    tmp.replace(p)
    return p


def _read_rotation(target_day: date) -> dict[str, Any] | None:
    p = _rotation_path(target_day)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("read rotation %s failed: %s", p, exc)
        return None


def snapshot_today_rotation(top_n: int = DEFAULT_TOP_N, *, persist: bool = True) -> dict[str, Any]:
    """akshare 90 行业当日 Top N, 按 changePct 排序, 落盘到 ``reference/stock-universe/market_pulse/rotation/YYYY-MM-DD.json``.

    Returns:
      {date, topN, items: [{name, changePct, mainNet, inflow, outflow, stockCount,
                              leadingStock, leadingChangePct, rank}, ...]}

    落盘策略:
      - 当日文件被覆盖 (收盘后重复跑保持最新).
      - 历史文件保留.
    """
    rows = _fetch_akshare_industry_spot() or []
    rows_with_chg = [r for r in rows if r.get("changePct") is not None]
    rows_with_chg.sort(key=lambda r: -(r.get("changePct") or 0))
    top = rows_with_chg[:top_n]
    today = date.today()

    out: dict[str, Any] = {
        "date": today.isoformat(),
        "topN": top_n,
        "items": [
            {
                "name":              r.get("name"),
                "changePct":         r.get("changePct"),
                "mainNet":           r.get("mainNet"),         # 亿
                "inflow":            r.get("inflow"),          # 亿
                "outflow":           r.get("outflow"),         # 亿
                "stockCount":        r.get("stockCount"),
                "leadingStock":      r.get("leadingStock"),
                "leadingChangePct":  r.get("leadingChangePct"),
                "rank":              idx + 1,
            }
            for idx, r in enumerate(top)
        ],
        "source": "akshare.stock_fund_flow_industry (10jqka)",
        "fetchedAt": datetime.now().isoformat(timespec="seconds"),
    }
    if persist:
        _write_rotation(today, out)
    return out


def build_industry_rotation(days: int = 10, top_n: int = DEFAULT_TOP_N) -> dict[str, Any]:
    """读过去 ``days`` 个交易日的行业轮动快照, 按日期倒序返回.

    行为:
      - 如果今日快照不存在, 先抓一份再继续.
      - 不足 ``days`` 个交易日就返实际有的 (不补).
    """
    today = date.today()
    today_snap = _read_rotation(today)
    if today_snap is None:
        try:
            today_snap = snapshot_today_rotation(top_n=top_n, persist=True)
        except Exception as exc:
            logger.warning("snapshot today rotation failed: %s", exc)
            today_snap = None

    rows: list[dict[str, Any]] = []
    if today_snap:
        rows.append(today_snap)

    # 历史快照: ROTATION_DIR 下所有非今日文件, 按文件名 (日期) 倒序
    if ROTATION_DIR.exists():
        files = sorted(ROTATION_DIR.glob("*.json"), reverse=True)
        for p in files:
            if len(rows) >= days:
                break
            if p.stem == today.isoformat():
                continue
            blob = _read_rotation(date.fromisoformat(p.stem))
            if blob:
                rows.append(blob)

    return {
        "ok": True,
        "topN": top_n,
        "dates": [r["date"] for r in rows],
        "rows": rows,
        "missingDates": [],  # 留扩展位
        "source": "reference/stock-universe/market_pulse/rotation/*.json",
    }


# ---------------------------------------------------------------------------
# 顶层入口: 一次拿三块 (前端首页加载)
# ---------------------------------------------------------------------------
def build_market_pulse() -> dict[str, Any]:
    return {
        "ok": True,
        "strong": build_strong_sectors(),
        "flow":   build_capital_flow(),
        "rotation": build_industry_rotation(),
    }


# ---------------------------------------------------------------------------
# 4. 跨日 Top 10 趋势: 同一行业在 N 个交易日内出现/消失/排名变化
# ---------------------------------------------------------------------------
def build_rotation_trend(days: int = 10, top_n: int = DEFAULT_TOP_N) -> dict[str, Any]:
    """读过去 ``days`` 个交易日的 rotation 快照, 汇总"行业跨日"信息.

    Returns:
      {
        ok, topN, dates,                # 涉及的所有日期 (倒序)
        industries: [                   # 每个出现过的行业 1 行
          { name, appearances,          # 出现次数
            ranks: [rank, rank, ...],   # 每个 date 对应的 rank (没出现 -> None)
            changePcts: [...],          # 每个 date 对应的 changePct
            avgRank, bestRank, worstRank, latestRank, latestChangePct
          }, ...
        ]
      }
    """
    today = date.today()
    rows: list[dict[str, Any]] = []
    if ROTATION_DIR.exists():
        files = sorted(ROTATION_DIR.glob("*.json"), reverse=True)
        for p in files:
            if len(rows) >= days:
                break
            blob = _read_rotation(date.fromisoformat(p.stem))
            if blob:
                rows.append(blob)
    # rows 是倒序 (新 -> 旧); 同时把 dates 给前端
    dates: list[str] = [r["date"] for r in rows]

    # 收集所有出现过的行业
    name_set: set[str] = set()
    for r in rows:
        for it in (r.get("items") or []):
            name_set.add(it.get("name") or "")

    industries: list[dict[str, Any]] = []
    for name in sorted(name_set):
        if not name:
            continue
        ranks: list[int | None] = []
        cps:   list[float | None] = []
        for r in rows:
            # rows 是新->旧
            item = next((x for x in (r.get("items") or []) if x.get("name") == name), None)
            if item:
                ranks.append(item.get("rank"))
                cps.append(item.get("changePct"))
            else:
                ranks.append(None)
                cps.append(None)
        appearances = sum(1 for v in ranks if v is not None)
        valid_ranks = [v for v in ranks if v is not None]
        latest_rank = ranks[0] if ranks and ranks[0] is not None else None
        latest_cp = cps[0] if cps and cps[0] is not None else None
        industries.append({
            "name": name,
            "appearances": appearances,
            "avgRank": round(sum(valid_ranks) / len(valid_ranks), 2) if valid_ranks else None,
            "bestRank": min(valid_ranks) if valid_ranks else None,
            "worstRank": max(valid_ranks) if valid_ranks else None,
            "latestRank": latest_rank,
            "latestChangePct": latest_cp,
            "ranks": ranks,        # [新->旧]
            "changePcts": cps,     # [新->旧]
        })

    # 默认按 "最新一次出现的排名" 升序, 没出现过的行业排到后面
    industries.sort(key=lambda x: (
        x["latestRank"] is None,
        x["latestRank"] if x["latestRank"] is not None else 10**6,
        -x["appearances"],
    ))

    return {
        "ok": True,
        "topN": top_n,
        "days": len(rows),
        "dates": dates,
        "industries": industries,
    }


# ---------------------------------------------------------------------------
# 5. M1 卡片钻入: 行业名 → 领涨股详情 + 该股 K 线 + 30 天资金流
# ---------------------------------------------------------------------------
def build_industry_detail(name: str, top_n: int = 30) -> dict[str, Any]:
    """按 90 行业名钻入, 返回领涨股 + 行情 + K 线 + 资金流."""
    spot = _fetch_akshare_industry_spot() or []
    info = next((r for r in spot if r.get("name") == name), None)
    if not info:
        return {
            "ok": False,
            "error": f"行业 {name!r} 不在 akshare 90 行业列表中",
            "name": name,
            "constituents": [],
        }

    leading = info.get("leadingStock")
    detail: dict[str, Any] = {
        "ok": True,
        "name": name,
        "changePct": info.get("changePct"),
        "mainNet": info.get("mainNet"),         # 亿
        "inflow": info.get("inflow"),
        "outflow": info.get("outflow"),
        "stockCount": info.get("stockCount"),
        "leadingStock": leading,
        "leadingChangePct": info.get("leadingChangePct"),
        "leadingQuote": None,
        "leadingKLine": [],
        "leadingFlow30d": [],
        "constituents": [],
    }

    if not leading:
        return detail

    # 1) 领涨股实时行情
    try:
        from backend.adapters.market.eltdx_adapter import _build_client
        client = _build_client()
        # 优先用 leading 当 code 找 full_code
        code = leading
        full = None
        for m in ("sh", "sz", "bj"):
            if code.startswith(m):
                full = code
                break
        if not full:
            # leading 形如 "中国银行" 时, 用 f10.search 不一定准, 直接尝试 sh 6位/sz 6位 prefix
            # akshare 领涨股给的就是 stock name, 没法直接当 code; 这里降级: 不拉 quote
            full = None
        if full:
            qs = client.get_quote([full]) or []
            if qs:
                q = qs[0]
                detail["leadingQuote"] = {
                    "fullCode": getattr(q, "full_code", None),
                    "code":     getattr(q, "code", None),
                    "name":     getattr(q, "name", None),
                    "lastPrice": getattr(q, "last_price", None),
                    "preClosePrice": getattr(q, "pre_close_price", None),
                    "change": getattr(q, "change", None),
                    "changePct": getattr(q, "change_pct", None),
                    "openPrice": getattr(q, "open_price", None),
                    "highPrice": getattr(q, "high_price", None),
                    "lowPrice":  getattr(q, "low_price", None),
                    "amount": getattr(q, "amount", None),
                    "totalHand": getattr(q, "total_hand", None),
                }
            # 2) 60 日 K
            try:
                series = client.bars.get(full, period="day", count=60)
                for b in (getattr(series, "bars", None) or []):
                    detail["leadingKLine"].append({
                        "time": getattr(b, "time", None),
                        "open": getattr(b, "open", None),
                        "high": getattr(b, "high", None),
                        "low":  getattr(b, "low", None),
                        "close": getattr(b, "close", None),
                        "amount": getattr(b, "amount", None),
                        "volume_lots": getattr(b, "volume_lots", None),
                    })
            except Exception as exc:
                logger.debug("bars.get(%s) failed: %s", full, exc)
    except Exception as exc:
        logger.debug("leading stock quote/kline failed: %s", exc)

    # 3) 领涨股 30 天主力资金
    try:
        from .f10.tdx_industry_seeds import seed_for
        # 用 leading 字符串本身当 seed, 不在 seed pool 也试一下
        for seed in (leading, *seed_for(_guess_code6_from_name(name) or "")):
            try:
                rows = get_main_capital_flow(seed) or []
            except Exception:
                continue
            if rows:
                detail["leadingFlow30d"] = [
                    {
                        "date": r.get("date"),
                        "mainNet":   r.get("main_net"),
                        "largeNet":  r.get("large_order_net"),
                        "mediumNet": r.get("medium_order_net"),
                        "smallNet":  r.get("small_order_net"),
                    }
                    for r in rows[:30]
                ]
                detail["leadingFlowSeed"] = seed
                break
    except Exception as exc:
        logger.debug("leading flow failed: %s", exc)

    # constituents 这里用 stockCount 表达, 不返回列表 (akshare 90 行业接口本身不返成分股)
    detail["constituents"] = []
    return detail


def _guess_code6_from_name(name: str) -> str | None:
    """粗略 90 行业名 → 56 行业 code 映射, 找不到返 None. 内部用."""
    # 这是一个小映射, 用于把 akshare 90 行业名反向到 TDX 56 行业 code (取首只 seed 试 200742)
    name_map: dict[str, str] = {
        "银行": "880471", "保险": "880473", "证券": "880472", "多元金融": "880474",
        "半导体": "880491", "通信设备": "880490", "元器件": "880492", "IT设备": "880489",
        "软件服务": "880493", "互联网": "880494",
        "酿酒": "880380", "食品饮料": "880372", "家用电器": "880387", "医药": "880400",
        "汽车类": "880390", "电气设备": "880446", "工业机械": "880440", "通用机械": "880437",
        "钢铁": "880318", "煤炭": "880301", "石油": "880310", "电力": "880305",
        "化纤": "880330", "化工": "880335", "造纸": "880350", "建材": "880344",
        "纺织服饰": "880367", "农林牧渔": "880360", "商业连锁": "880406",
    }
    return name_map.get(name)
