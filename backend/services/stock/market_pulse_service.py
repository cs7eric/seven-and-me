r"""Stock Overview · Market Pulse service backed by Postgres snapshots.

维护前请先看:
`F:\dev-repo\mp4-to-word-new\design\backend\market-pulse-postgres-migration.md`

后续如果调整抓取时机、交易日回退规则、表结构、API 返回字段或历史导入逻辑，
请先更新设计文档，再修改这里；改完代码后也要同步回写 design 文档。
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from backend.config.database import session_scope
from backend.repositories.market.market_pulse_pg_repo import MarketPulseRepository
from backend.utils.trading_day import (
    beijing_now,
    beijing_today,
    can_request_live_fund_flow_snapshot,
    resolve_fund_flow_read_trade_date,
)

from .sector_quote_service import get_main_capital_flow
from .f10.ths_industry_service import name_to_code

logger = logging.getLogger(__name__)

try:
    import akshare as ak  # noqa: F401

    _AKSHARE_AVAILABLE = True
except ImportError:
    _AKSHARE_AVAILABLE = False
    logger.warning("akshare not installed; market pulse live capture disabled")

DEFAULT_TOP_N = 10
DEFAULT_FLOW_TOP_N = 20
DEFAULT_ROTATION_DAYS = 10
COMPOSITE_WINDOW_DAYS = 30
COMPOSITE_FLOW_AVG_WINDOW = 10
MAX_INDUSTRY_COMPARE_COUNT = 20
_LIVE_REFRESH_SECONDS = 10 * 60


def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return f


def _fetch_one_flow_akshare() -> list[dict[str, Any]] | None:
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
            out.append(
                {
                    "name": str(row.get("行业") or "").strip(),
                    "index": str(row.get("行业指数") or "").strip() or None,
                    "changePct": _to_float(row.get("行业-涨跌幅")),
                    "inflow": _to_float(row.get("流入资金")) or 0.0,
                    "outflow": _to_float(row.get("流出资金")) or 0.0,
                    "mainNet": _to_float(row.get("净额")) or 0.0,
                    "stockCount": int(row.get("公司家数") or 0),
                    "leadingStock": str(row.get("领涨股") or "").strip() or None,
                    "leadingChangePct": _to_float(row.get("领涨股-涨跌幅")),
                    "leadingPrice": _to_float(row.get("当前价")),
                }
            )
        except Exception as exc:
            logger.debug("market pulse akshare row parse failed: %s", exc)
    return [row for row in out if row.get("name")]


def _build_snapshot_payload(rows: list[dict[str, Any]], trade_date: str, top_n: int) -> dict[str, Any]:
    top = rows[:top_n]
    return {
        "date": trade_date,
        "topN": top_n,
        "items": [
            {
                "name": row.get("name"),
                "changePct": row.get("changePct"),
                "mainNet": row.get("mainNet"),
                "inflow": row.get("inflow"),
                "outflow": row.get("outflow"),
                "stockCount": row.get("stockCount"),
                "leadingStock": row.get("leadingStock"),
                "leadingChangePct": row.get("leadingChangePct"),
                "leadingPrice": row.get("leadingPrice"),
                "rank": row.get("rank"),
            }
            for row in top
        ],
    }


def _get_resolved_snapshot(*, force_refresh: bool = False) -> dict[str, Any]:
    now = beijing_now()
    today = beijing_today()
    read_trade_date = resolve_fund_flow_read_trade_date(now=now)

    with session_scope() as db:
        repo = MarketPulseRepository(db)
        repo.ensure_bootstrapped()

        if can_request_live_fund_flow_snapshot(today, now=now):
            batch = repo.get_trade_day_batch(today)
            should_refresh = (
                force_refresh
                or batch is None
                or (now - batch.fetched_at.replace(tzinfo=None)).total_seconds() >= _LIVE_REFRESH_SECONDS
            )
            if should_refresh:
                live_rows = _fetch_one_flow_akshare() or []
                if live_rows:
                    repo.replace_trade_day_snapshot(
                        trade_date=today,
                        rows=live_rows,
                        source_kind="live_capture",
                        source_name="akshare.stock_fund_flow_industry",
                        fetched_at=now,
                        extra={"capturedDuringTrading": True},
                        remark="live market pulse capture",
                    )

        actual_trade_date = repo.latest_trade_date(end=read_trade_date) or repo.latest_trade_date()
        if actual_trade_date is None:
            return {
                "tradeDate": None,
                "requestedTradeDate": read_trade_date.isoformat(),
                "isFallbackTradeDate": False,
                "rows": [],
                "source": "postgres.market_pulse",
                "sourceKind": None,
                "fetchedAt": now.isoformat(timespec="seconds"),
            }
        batch = repo.get_trade_day_batch(actual_trade_date)
        rows = repo.get_trade_day_rows(actual_trade_date)
        return {
            "tradeDate": actual_trade_date.isoformat(),
            "requestedTradeDate": read_trade_date.isoformat(),
            "isFallbackTradeDate": actual_trade_date != read_trade_date,
            "rows": rows,
            "source": batch.source_name if batch else "postgres.market_pulse",
            "fetchedAt": (batch.fetched_at if batch else now).isoformat(timespec="seconds"),
            "sourceKind": batch.source_kind if batch else None,
            "status": batch.status if batch else None,
        }


def build_strong_sectors(top_n: int = DEFAULT_TOP_N, *, force_refresh: bool = False) -> dict[str, Any]:
    snapshot = _get_resolved_snapshot(force_refresh=force_refresh)
    rows = list(snapshot["rows"])
    top = rows[:top_n]
    bottom = list(reversed(rows[-min(top_n, len(rows)) :]))
    for row in top + bottom:
        row["amount"] = (row.get("mainNet") or 0) * 1e8
        row["changePercent"] = row.get("changePct")
    return {
        "ok": True,
        "kind": "postgres.market_pulse",
        "label": "行业",
        "tradeDate": snapshot["tradeDate"],
        "top": top,
        "bottom": bottom,
        "count": len(rows),
        "topN": top_n,
        "fetchedAt": snapshot["fetchedAt"],
        "source": snapshot["source"],
        "sourceKind": snapshot["sourceKind"],
        "requestedTradeDate": snapshot["requestedTradeDate"],
        "isFallbackTradeDate": snapshot["isFallbackTradeDate"],
    }


def build_capital_flow(top_n: int = DEFAULT_FLOW_TOP_N, *, force_refresh: bool = False) -> dict[str, Any]:
    snapshot = _get_resolved_snapshot(force_refresh=force_refresh)
    rows = list(snapshot["rows"])
    inflow = sorted([row for row in rows if (row.get("mainNet") or 0) > 0], key=lambda row: -(row.get("mainNet") or 0))
    outflow = sorted([row for row in rows if (row.get("mainNet") or 0) <= 0], key=lambda row: row.get("mainNet") or 0)
    return {
        "ok": True,
        "kind": "postgres.market_pulse",
        "tradeDate": snapshot["tradeDate"],
        "inflow": inflow[:top_n],
        "outflow": outflow[:top_n],
        "inflowCount": len(inflow),
        "outflowCount": len(outflow),
        "count": len(rows),
        "totalIndustries": len(rows),
        "elapsedMs": 0,
        "fetchedAt": snapshot["fetchedAt"],
        "source": snapshot["source"],
        "sourceKind": snapshot["sourceKind"],
        "requestedTradeDate": snapshot["requestedTradeDate"],
        "isFallbackTradeDate": snapshot["isFallbackTradeDate"],
        "unit": "亿",
    }


def snapshot_today_rotation(top_n: int = DEFAULT_TOP_N, *, persist: bool = True) -> dict[str, Any]:
    snapshot = _get_resolved_snapshot(force_refresh=bool(persist))
    rows = list(snapshot["rows"])
    payload = (
        _build_snapshot_payload(rows, snapshot["tradeDate"], top_n)
        if snapshot["tradeDate"]
        else {"date": None, "topN": top_n, "items": []}
    )
    payload["source"] = snapshot["source"]
    payload["sourceKind"] = snapshot["sourceKind"]
    payload["fetchedAt"] = snapshot["fetchedAt"]
    payload["requestedTradeDate"] = snapshot["requestedTradeDate"]
    payload["isFallbackTradeDate"] = snapshot["isFallbackTradeDate"]
    payload["persisted"] = bool(persist and snapshot["tradeDate"] == beijing_today().isoformat())
    return payload


def build_industry_rotation(
    days: int = DEFAULT_ROTATION_DAYS,
    top_n: int = DEFAULT_TOP_N,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    _get_resolved_snapshot(force_refresh=force_refresh)
    with session_scope() as db:
        repo = MarketPulseRepository(db)
        repo.ensure_bootstrapped()
        dates = repo.list_trade_dates(limit=max(1, min(days, 365)))
        rows = []
        for trade_date in dates:
            day_rows = repo.get_trade_day_rows(trade_date)
            rows.append(_build_snapshot_payload(day_rows, trade_date, top_n))
    return {
        "ok": True,
        "topN": top_n,
        "dates": dates,
        "rows": rows,
        "missingDates": [],
        "source": "postgres.market_pulse",
        "requestedTradeDate": dates[0] if dates else None,
    }


def build_market_pulse(
    *,
    days: int = DEFAULT_ROTATION_DAYS,
    top_n: int = DEFAULT_TOP_N,
    flow_top_n: int = DEFAULT_FLOW_TOP_N,
    force_refresh: bool = False,
) -> dict[str, Any]:
    snapshot = _get_resolved_snapshot(force_refresh=force_refresh)
    rows = list(snapshot["rows"])
    top = rows[:top_n]
    bottom = list(reversed(rows[-min(top_n, len(rows)) :]))
    for row in top + bottom:
        row["amount"] = (row.get("mainNet") or 0) * 1e8
        row["changePercent"] = row.get("changePct")

    inflow = sorted([row for row in rows if (row.get("mainNet") or 0) > 0], key=lambda row: -(row.get("mainNet") or 0))
    outflow = sorted([row for row in rows if (row.get("mainNet") or 0) <= 0], key=lambda row: row.get("mainNet") or 0)

    with session_scope() as db:
        repo = MarketPulseRepository(db)
        repo.ensure_bootstrapped()
        dates = repo.list_trade_dates(limit=max(1, min(days, 365)))
        rotation_rows = []
        for trade_date in dates:
            day_rows = repo.get_trade_day_rows(trade_date)
            rotation_rows.append(_build_snapshot_payload(day_rows, trade_date, top_n))

    return {
        "ok": True,
        "strong": {
            "ok": True,
            "kind": "postgres.market_pulse",
            "label": "行业",
            "tradeDate": snapshot["tradeDate"],
            "top": top,
            "bottom": bottom,
            "count": len(rows),
            "topN": top_n,
            "fetchedAt": snapshot["fetchedAt"],
            "source": snapshot["source"],
            "sourceKind": snapshot["sourceKind"],
            "requestedTradeDate": snapshot["requestedTradeDate"],
            "isFallbackTradeDate": snapshot["isFallbackTradeDate"],
        },
        "flow": {
            "ok": True,
            "kind": "postgres.market_pulse",
            "tradeDate": snapshot["tradeDate"],
            "inflow": inflow[:flow_top_n],
            "outflow": outflow[:flow_top_n],
            "inflowCount": len(inflow),
            "outflowCount": len(outflow),
            "count": len(rows),
            "totalIndustries": len(rows),
            "elapsedMs": 0,
            "fetchedAt": snapshot["fetchedAt"],
            "source": snapshot["source"],
            "sourceKind": snapshot["sourceKind"],
            "requestedTradeDate": snapshot["requestedTradeDate"],
            "isFallbackTradeDate": snapshot["isFallbackTradeDate"],
            "unit": "亿",
        },
        "rotation": {
            "ok": True,
            "tradeDate": snapshot["tradeDate"],
            "topN": top_n,
            "dates": dates,
            "rows": rotation_rows,
            "missingDates": [],
            "source": "postgres.market_pulse",
            "sourceKind": snapshot["sourceKind"],
            "requestedTradeDate": snapshot["requestedTradeDate"],
            "isFallbackTradeDate": snapshot["isFallbackTradeDate"],
        },
    }


def build_rotation_trend(days: int = DEFAULT_ROTATION_DAYS, top_n: int = DEFAULT_TOP_N) -> dict[str, Any]:
    from backend.repositories.market.ths_industry_fund_flow_repo import ThsIndustryFundFlowRepository

    with session_scope() as db:
        repo = MarketPulseRepository(db)
        repo.ensure_bootstrapped()
        dates = repo.list_trade_dates(limit=max(1, min(days, 365)))
        daily_rows: list[dict[str, Any]] = []
        for trade_date in dates:
            daily_rows.append(_build_snapshot_payload(repo.get_trade_day_rows(trade_date), trade_date, top_n))

        flow_repo = ThsIndustryFundFlowRepository(db)
        flow_repo.ensure_bootstrapped()
        flow_rows = flow_repo.get_fund_flow_history(days=max(COMPOSITE_WINDOW_DAYS, COMPOSITE_FLOW_AVG_WINDOW))

    name_set: set[str] = set()
    for row in daily_rows:
        for item in row.get("items") or []:
            name = item.get("name")
            if name:
                name_set.add(name)

    flow_series_map: dict[str, list[float | None]] = {}
    for row in flow_rows:
        for item in row.get("items") or []:
            name = str(item.get("name") or "").strip()
            if not name or name not in name_set:
                continue
            flow_series_map.setdefault(name, []).append(item.get("mainNet"))
    for values in flow_series_map.values():
        values.reverse()

    window_days = min(len(dates), COMPOSITE_WINDOW_DAYS)
    industries: list[dict[str, Any]] = []
    for name in sorted(name_set):
        ranks: list[int | None] = []
        cps: list[float | None] = []
        for row in daily_rows:
            item = next((it for it in (row.get("items") or []) if it.get("name") == name), None)
            if item is None:
                ranks.append(None)
                cps.append(None)
                continue
            ranks.append(item.get("rank"))
            cps.append(item.get("changePct"))
        recent_ranks = ranks[:window_days]
        valid_recent_ranks = [rank for rank in recent_ranks if rank is not None]
        appearances = len(valid_recent_ranks)
        latest_rank = ranks[0] if ranks else None
        latest_cp = cps[0] if cps else None
        avg_main_net_10 = _avg_latest_window(flow_series_map.get(name, []), COMPOSITE_FLOW_AVG_WINDOW)
        industries.append(
            {
                "name": name,
                "appearances": appearances,
                "avgRank": round(sum(valid_recent_ranks) / len(valid_recent_ranks), 2) if valid_recent_ranks else None,
                "bestRank": min(valid_recent_ranks) if valid_recent_ranks else None,
                "worstRank": max(valid_recent_ranks) if valid_recent_ranks else None,
                "latestRank": latest_rank,
                "latestChangePct": latest_cp,
                "avgMainNet10": avg_main_net_10,
                "ranks": ranks,
                "changePcts": cps,
            }
        )

    composite_meta = _build_composite_meta(industries, top_n=top_n, window_days=max(window_days, 1))
    for item in industries:
        meta = composite_meta.get(str(item.get("name") or ""), {})
        item["appearanceRate"] = meta.get("appearanceRate")
        item["avgRankScore"] = meta.get("avgRankScore")
        item["flowScore"] = meta.get("flowScore")
        item["compositeScore"] = meta.get("compositeScore")
        item["compositeRank"] = meta.get("compositeRank")

    industries.sort(
        key=lambda row: (
            row.get("compositeRank") is None,
            row.get("compositeRank") if row.get("compositeRank") is not None else 10**6,
            row["latestRank"] is None,
            row["latestRank"] if row["latestRank"] is not None else 10**6,
            -row["appearances"],
        )
    )
    return {
        "ok": True,
        "topN": top_n,
        "days": len(dates),
        "compositeWindowDays": window_days,
        "dates": dates,
        "industries": industries,
    }


def _avg_latest_window(values: list[float | None], window: int) -> float | None:
    valid = [value for value in values if value is not None]
    if len(valid) < window:
        return None
    sample = valid[-window:]
    return round(sum(sample) / window, 4)


def _rank_to_unit_interval(index: int, total: int) -> float:
    if total <= 1:
        return 1.0
    return round((total - index - 1) / (total - 1), 4)


def _build_composite_meta(
    trend_industries: list[dict[str, Any]],
    *,
    top_n: int,
    window_days: int,
) -> dict[str, dict[str, float | int | None]]:
    if not trend_industries or window_days <= 0:
        return {}

    flow_ranked = [item for item in trend_industries if isinstance(item.get("avgMainNet10"), (int, float))]
    flow_ranked.sort(
        key=lambda item: (
            -(item.get("avgMainNet10") or 0),
            item.get("name") or "",
        )
    )
    flow_scores = {
        str(item.get("name") or ""): _rank_to_unit_interval(index, len(flow_ranked))
        for index, item in enumerate(flow_ranked)
        if item.get("name")
    }

    scored: list[dict[str, Any]] = []
    for item in trend_industries:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        appearances = int(item.get("appearances") or 0)
        avg_rank = item.get("avgRank")
        appearance_rate = round(appearances / window_days, 4)
        avg_rank_score = 0.0
        if isinstance(avg_rank, (int, float)) and top_n > 0:
            avg_rank_score = max(0.0, min(1.0, (top_n + 1 - float(avg_rank)) / top_n))
        flow_score = flow_scores.get(name, 0.0)
        composite_score = round(0.5 * appearance_rate + 0.3 * avg_rank_score + 0.2 * flow_score, 4)
        scored.append(
            {
                "name": name,
                "appearanceRate": appearance_rate,
                "avgRankScore": round(avg_rank_score, 4),
                "flowScore": flow_score,
                "compositeScore": composite_score,
                "latestRank": item.get("latestRank"),
                "latestChangePct": item.get("latestChangePct"),
            }
        )

    scored.sort(
        key=lambda item: (
            -item["compositeScore"],
            item["latestRank"] is None,
            item["latestRank"] if item["latestRank"] is not None else 10**6,
            -(item["latestChangePct"] or 0),
            item["name"],
        )
    )
    return {
        item["name"]: {
            "appearanceRate": item["appearanceRate"],
            "avgRankScore": item["avgRankScore"],
            "flowScore": item["flowScore"],
            "compositeScore": item["compositeScore"],
            "compositeRank": index + 1,
        }
        for index, item in enumerate(scored)
    }


def build_industry_compare(
    names: list[str],
    *,
    days: int = 120,
    end: str | None = None,
) -> dict[str, Any]:
    picked_names: list[str] = []
    seen: set[str] = set()
    for raw_name in names:
        name = str(raw_name or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        picked_names.append(name)
    picked_names = picked_names[:MAX_INDUSTRY_COMPARE_COUNT]

    from backend.repositories.market.ths_industry_fund_flow_repo import ThsIndustryFundFlowRepository

    with session_scope() as db:
        repo = ThsIndustryFundFlowRepository(db)
        repo.ensure_bootstrapped()
        dates_desc = repo.list_trade_dates(limit=max(1, min(days, 365)))
        if end:
            dates_desc = [trade_date for trade_date in dates_desc if trade_date <= end]
        dates = list(reversed(dates_desc))
        industries: list[dict[str, Any]] = []
        for name in picked_names:
            rows = repo.get_fund_flow_for_industry(name, days=max(1, min(days, 365)), end=end)
            row_map = {str(row.get("tradeDate") or ""): row for row in rows if row.get("tradeDate")}
            points: list[dict[str, Any]] = []
            net_series: list[float | None] = []
            for trade_date in dates:
                row = row_map.get(trade_date)
                main_net = row.get("净额(亿)") if row else None
                rank = row.get("序号") if row else None
                change_pct = row.get("行业指数涨跌幅") if row else None
                points.append({"date": trade_date, "mainNet": main_net, "rank": rank, "changePct": change_pct})
                net_series.append(main_net if isinstance(main_net, (int, float)) else None)

            latest_point = next(
                (
                    point
                    for point in reversed(points)
                    if point.get("mainNet") is not None or point.get("rank") is not None
                ),
                None,
            )
            industries.append(
                {
                    "name": name,
                    "days": len(points),
                    "appearances": sum(1 for point in points if point.get("rank") is not None),
                    "latestMainNet": latest_point.get("mainNet") if latest_point else None,
                    "latestRank": latest_point.get("rank") if latest_point else None,
                    "latestChangePct": latest_point.get("changePct") if latest_point else None,
                    "averages": {
                        "5": _avg_latest_window(net_series, 5),
                        "10": _avg_latest_window(net_series, 10),
                        "30": _avg_latest_window(net_series, 30),
                        "60": _avg_latest_window(net_series, 60),
                    },
                    "points": points,
                }
            )

    return {
        "ok": True,
        "days": len(dates),
        "dates": dates,
        "requestedIndustries": picked_names,
        "count": len(industries),
        "industries": industries,
    }


def build_industry_detail(name: str, top_n: int = 30) -> dict[str, Any]:
    snapshot = _get_resolved_snapshot(force_refresh=False)
    with session_scope() as db:
        repo = MarketPulseRepository(db)
        repo.ensure_bootstrapped()
        info = repo.get_sector_row(snapshot["tradeDate"], name) if snapshot["tradeDate"] else None

    if not info:
        return {
            "ok": False,
            "error": f"行业 {name!r} 不在 market pulse 快照中",
            "name": name,
            "constituents": [],
        }

    leading = info.get("leadingStock")
    detail: dict[str, Any] = {
        "ok": True,
        "name": name,
        "tradeDate": snapshot["tradeDate"],
        "changePct": info.get("changePct"),
        "mainNet": info.get("mainNet"),
        "inflow": info.get("inflow"),
        "outflow": info.get("outflow"),
        "stockCount": info.get("stockCount"),
        "leadingStock": leading,
        "leadingChangePct": info.get("leadingChangePct"),
        "leadingQuote": None,
        "leadingKLine": [],
        "leadingFlow30d": [],
        "constituents": [],
        "industryCode": name_to_code(name),
    }

    if not leading:
        return detail

    try:
        from backend.adapters.market.eltdx_adapter import _build_client

        client = _build_client()
        full = None
        if isinstance(leading, str) and leading.lower().startswith(("sh", "sz", "bj")):
            full = leading
        if full:
            qs = client.get_quote([full]) or []
            if qs:
                q = qs[0]
                detail["leadingQuote"] = {
                    "fullCode": getattr(q, "full_code", None),
                    "code": getattr(q, "code", None),
                    "name": getattr(q, "name", None),
                    "lastPrice": getattr(q, "last_price", None),
                    "preClosePrice": getattr(q, "pre_close_price", None),
                    "change": getattr(q, "change", None),
                    "changePct": getattr(q, "change_pct", None),
                    "openPrice": getattr(q, "open_price", None),
                    "highPrice": getattr(q, "high_price", None),
                    "lowPrice": getattr(q, "low_price", None),
                    "amount": getattr(q, "amount", None),
                    "totalHand": getattr(q, "total_hand", None),
                }
            try:
                series = client.bars.get(full, period="day", count=60)
                for bar in getattr(series, "bars", None) or []:
                    detail["leadingKLine"].append(
                        {
                            "time": getattr(bar, "time", None),
                            "open": getattr(bar, "open", None),
                            "high": getattr(bar, "high", None),
                            "low": getattr(bar, "low", None),
                            "close": getattr(bar, "close", None),
                            "amount": getattr(bar, "amount", None),
                            "volume_lots": getattr(bar, "volume_lots", None),
                        }
                    )
            except Exception as exc:
                logger.debug("market pulse leading bars failed: %s", exc)
    except Exception as exc:
        logger.debug("market pulse leading quote failed: %s", exc)

    try:
        for seed in (leading,):
            try:
                rows = get_main_capital_flow(seed) or []
            except Exception:
                continue
            if rows:
                detail["leadingFlow30d"] = [
                    {
                        "date": row.get("date"),
                        "mainNet": row.get("main_net"),
                        "largeNet": row.get("large_order_net"),
                        "mediumNet": row.get("medium_order_net"),
                        "smallNet": row.get("small_order_net"),
                    }
                    for row in rows[:top_n]
                ]
                detail["leadingFlowSeed"] = seed
                break
    except Exception as exc:
        logger.debug("market pulse leading flow failed: %s", exc)

    return detail


__all__ = [
    "build_capital_flow",
    "build_industry_compare",
    "build_industry_detail",
    "build_industry_rotation",
    "build_market_pulse",
    "build_rotation_trend",
    "build_strong_sectors",
    "snapshot_today_rotation",
]
