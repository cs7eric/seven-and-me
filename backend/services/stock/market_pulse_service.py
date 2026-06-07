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

# 持久化目录: 每个交易日一份快照
ROTATION_DIR: Final[Path] = STOCK_UNIVERSE_DIR / "market_pulse" / "rotation"
ROTATION_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_TOP_N: Final[int] = 10
DEFAULT_FLOW_DAYS: Final[int] = 30


# ---------------------------------------------------------------------------
# 1. 强势板块 - 直接复用 tdx_industry_service
# ---------------------------------------------------------------------------
def build_strong_sectors(top_n: int = DEFAULT_TOP_N) -> dict[str, Any]:
    """TDX 56 行业指数, 按 change_pct 排序, 取 top N.

    数据源: eltdx.get_index_codes_all + get_quote. 跟 heatmap 行业屏同源.
    """
    payload = build_industry_market_payload()
    rows = payload.get("items") or []
    rows = [r for r in rows if r.get("changePercent") is not None]
    rows.sort(key=lambda r: -(r.get("changePercent") or 0))

    top = rows[:top_n]
    bottom = list(reversed(rows[-min(top_n, len(rows)):]))
    return {
        "ok": True,
        "kind": "industries",
        "label": payload.get("label", "行业"),
        "top": top,
        "bottom": bottom,
        "count": len(rows),
        "topN": top_n,
        "fetchedAt": payload.get("fetchedAt"),
        "source": payload.get("source", "tdx_industry_service"),
    }


# ---------------------------------------------------------------------------
# 2. 行业主力净流入 - eltdx 200742
# ---------------------------------------------------------------------------
def _pick_seed_for_industry(code6: str) -> str | None:
    """从 :data:`TDX_INDUSTRY_56` 旁的 seed 池里选一只 seed.

    行业指数 8803XX 自身没有 200742 响应, 200742 必须传"种子股".
    seed 池见 ``tdx_industry_seeds.py``. 这里直接走 top1, 不通就在循环层重试.
    """
    from .f10.tdx_industry_seeds import seed_for
    seeds = seed_for(code6)
    return seeds[0] if seeds else None


def _fetch_one_flow(code6: str, name: str, days: int) -> dict[str, Any] | None:
    """单个行业拉 30 天主力净流入; 选 seed 池里第一个能拿到数据的.

    返回:
      {
        code6, name, seed,
        mainNet, largeNet, mediumNet, smallNet,           # 当日 (最近 1 天)
        mainNetPct,                                        # 主力净额 / 板块成交额
        consecutiveDays,                                   # 连续净流入天数, 负数=连续净流出
        daily: [{date, mainNet, largeNet, mediumNet, smallNet}]
      }
    """
    from .f10.tdx_industry_seeds import seed_for
    for seed in seed_for(code6):
        try:
            rows = get_main_capital_flow(seed) or []
        except Exception as exc:
            logger.debug("200742 failed for %s / seed %s: %s", code6, seed, exc)
            continue
        if not rows:
            continue
        # 按 date 倒序, 取最近 N 天
        rows_sorted = sorted(rows, key=lambda r: r.get("date") or "", reverse=True)[:days]
        latest = rows_sorted[0] if rows_sorted else None
        if not latest:
            continue

        # 连续净流入 / 净流出天数
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

        main_net = float(latest.get("main_net") or 0)
        return {
            "code6": code6,
            "name": name,
            "seed": seed,
            "date": latest.get("date"),
            "mainNet": main_net,
            "largeNet": float(latest.get("large_order_net") or 0),
            "mediumNet": float(latest.get("medium_order_net") or 0),
            "smallNet": float(latest.get("small_order_net") or 0),
            "mainNetPct": None,  # 前端不依赖, 留空
            "consecutiveDays": streak,
            "daily": [
                {
                    "date": r.get("date"),
                    "mainNet": float(r.get("main_net") or 0),
                    "largeNet": float(r.get("large_order_net") or 0),
                    "mediumNet": float(r.get("medium_order_net") or 0),
                    "smallNet": float(r.get("small_order_net") or 0),
                }
                for r in rows_sorted
            ],
        }
    return None


def build_capital_flow(days: int = DEFAULT_FLOW_DAYS, top_n: int = 20) -> dict[str, Any]:
    """56 行业并发拉 eltdx 200742 主力资金, 取最近 ``days`` 天."""
    t0 = datetime.now()
    results: list[dict[str, Any]] = []
    items = list(TDX_INDUSTRY_56.items())

    with ThreadPoolExecutor(max_workers=24, thread_name_prefix="flow-200742") as pool:
        futures = {
            pool.submit(_fetch_one_flow, c6, name, days): c6
            for c6, name in items
        }
        for fut, c6 in futures.items():
            try:
                row = fut.result(timeout=30)
            except Exception as exc:
                logger.warning("flow %s failed: %s", c6, exc)
                continue
            if row:
                results.append(row)

    inflow = sorted([r for r in results if r["mainNet"] > 0], key=lambda r: -r["mainNet"])
    outflow = sorted([r for r in results if r["mainNet"] < 0], key=lambda r: r["mainNet"])

    elapsed_ms = int((datetime.now() - t0).total_seconds() * 1000)
    return {
        "ok": True,
        "days": days,
        "inflow": inflow[:top_n],
        "outflow": outflow[:top_n],
        "inflowCount": len(inflow),
        "outflowCount": len(outflow),
        "count": len(results),
        "totalIndustries": len(items),
        "elapsedMs": elapsed_ms,
        "fetchedAt": datetime.now().isoformat(timespec="seconds"),
        "source": "eltdx.f10.theme_market(200742)",
    }


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
    """抓 TDX 56 行业指数当日, 按 change_pct 排序取 Top N.

    Returns:
      {date, items: [{code6, name, changePct, rank}, ...]}

    落盘策略:
      - 当日 (按 trading_day 算) 文件被覆盖, 这样可以"收盘后重复跑"保持最新.
      - 历史文件保留 (不再覆盖非今日).
    """
    payload = build_industry_market_payload()
    items = [r for r in (payload.get("items") or []) if r.get("changePercent") is not None]
    items.sort(key=lambda r: -(r.get("changePercent") or 0))
    top = items[:top_n]
    today = date.today()

    out: dict[str, Any] = {
        "date": today.isoformat(),
        "topN": top_n,
        "items": [
            {
                "code6": r.get("code6"),
                "name": r.get("name"),
                "fullCode": r.get("fullCode"),
                "changePct": r.get("changePercent"),
                "amount": r.get("amount"),
                "rank": idx + 1,
            }
            for idx, r in enumerate(top)
        ],
        "source": payload.get("source", "tdx_industry_service"),
        "fetchedAt": payload.get("fetchedAt"),
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
