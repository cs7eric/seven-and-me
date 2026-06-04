from __future__ import annotations

import json
from datetime import datetime
from math import isfinite
from statistics import mean, median
from typing import Any

from backend.services.stock.analysis_data_reader import (
    ReadResult,
    StockAnalysisDataReader,
    create_default_stock_analysis_data_reader,
)

DEFAULT_MAX_INPUT_CHARS = 1_000_000


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(out):
        return None
    return out


def _int(value: Any) -> int | None:
    number = _num(value)
    if number is None:
        return None
    return int(number)


def _round(value: Any, digits: int = 4) -> float | None:
    number = _num(value)
    if number is None:
        return None
    return round(number, digits)


def _pct(now: Any, base: Any, digits: int = 2) -> float | None:
    current = _num(now)
    previous = _num(base)
    if current is None or previous in (None, 0):
        return None
    return round((current - previous) / previous * 100, digits)


def _ratio(now: Any, base: Any, digits: int = 4) -> float | None:
    current = _num(now)
    previous = _num(base)
    if current is None or previous in (None, 0):
        return None
    return round(current / previous, digits)


def _avg(values: list[float]) -> float | None:
    cleaned = [value for value in values if value is not None and isfinite(value)]
    if not cleaned:
        return None
    return mean(cleaned)


def _safe_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _safe_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _timestamp_to_date(value: Any) -> str | None:
    ts = _int(value)
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
    except (OSError, ValueError, OverflowError):
        return None


def _bar_timestamp(item: dict[str, Any]) -> int:
    ts = _int(item.get("timestamp"))
    if ts:
        return ts
    text = str(item.get("trade_date") or item.get("date") or "").strip()
    if not text:
        return 0
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return int(datetime.strptime(text, fmt).timestamp() * 1000)
        except ValueError:
            continue
    return 0


def _normalize_bar(item: dict[str, Any]) -> dict[str, Any]:
    timestamp = _bar_timestamp(item)
    return {
        "timestamp": timestamp,
        "date": item.get("trade_date") or item.get("date") or _timestamp_to_date(timestamp),
        "open": _round(item.get("open"), 4),
        "high": _round(item.get("high"), 4),
        "low": _round(item.get("low"), 4),
        "close": _round(item.get("close"), 4),
        "volume": _round(item.get("volume"), 2),
        "amount": _round(item.get("turnover") if item.get("turnover") not in (None, 0) else item.get("amount"), 2),
        "turnover_rate": _round(item.get("turnover_rate"), 4),
        "volume_ratio": _round(item.get("volume_ratio"), 4),
    }


def _normalize_bars(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bars = [_normalize_bar(item) for item in items if isinstance(item, dict)]
    bars = [item for item in bars if item.get("timestamp") and item.get("close") is not None]
    bars.sort(key=lambda item: int(item.get("timestamp") or 0))
    return bars


def _window(values: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    if days <= 0:
        return []
    return values[-days:]


def _support_resistance(bars: list[dict[str, Any]], windows: list[int]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    latest_close = bars[-1].get("close") if bars else None
    for days in windows:
        sample = _window(bars, days)
        highs = [_num(item.get("high")) for item in sample]
        lows = [_num(item.get("low")) for item in sample]
        highs = [item for item in highs if item is not None]
        lows = [item for item in lows if item is not None]
        if not highs or not lows:
            continue
        high = max(highs)
        low = min(lows)
        out[f"{days}d"] = {
            "high": round(high, 4),
            "low": round(low, 4),
            "position": _ratio((_num(latest_close) or low) - low, high - low, 4) if high != low else None,
            "distance_to_high_pct": _pct(latest_close, high),
            "distance_to_low_pct": _pct(latest_close, low),
        }
    return out


def _trend_streak(bars: list[dict[str, Any]]) -> dict[str, Any]:
    if len(bars) < 2:
        return {"direction": "unknown", "days": 0}
    direction = 0
    days = 0
    for index in range(len(bars) - 1, 0, -1):
        close = _num(bars[index].get("close"))
        previous = _num(bars[index - 1].get("close"))
        if close is None or previous is None or close == previous:
            break
        step = 1 if close > previous else -1
        if direction == 0:
            direction = step
        if step != direction:
            break
        days += 1
    label = "up" if direction > 0 else "down" if direction < 0 else "flat"
    return {"direction": label, "days": days}


def _atr_pct(bars: list[dict[str, Any]], days: int = 14) -> float | None:
    if len(bars) < 2:
        return None
    ranges: list[float] = []
    sample = bars[-days:]
    previous_close = _num(bars[-len(sample) - 1].get("close")) if len(bars) > len(sample) else None
    for bar in sample:
        high = _num(bar.get("high"))
        low = _num(bar.get("low"))
        if high is None or low is None:
            continue
        if previous_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - previous_close), abs(low - previous_close))
        ranges.append(tr)
        previous_close = _num(bar.get("close"))
    avg_range = _avg(ranges)
    close = _num(bars[-1].get("close")) if bars else None
    if avg_range is None or close in (None, 0):
        return None
    return round(avg_range / close * 100, 2)


def summarize_bars(raw_items: list[dict[str, Any]], *, period: str, keep_recent: int = 12) -> dict[str, Any]:
    bars = _normalize_bars(raw_items)
    if not bars:
        return {"period": period, "count": 0, "warnings": ["no kline bars"]}

    latest = bars[-1]
    close = _num(latest.get("close"))
    volumes = [_num(item.get("volume")) for item in bars]
    volumes = [item for item in volumes if item is not None]
    amounts = [_num(item.get("amount")) for item in bars]
    amounts = [item for item in amounts if item is not None and item > 0]
    turnover_rates = [_num(item.get("turnover_rate")) for item in bars]
    turnover_rates = [item for item in turnover_rates if item is not None and item > 0]

    windows = [3, 5, 10, 20, 30, 60, 120, 250]
    returns: dict[str, float | None] = {}
    moving_average: dict[str, dict[str, Any]] = {}
    volume_stats: dict[str, dict[str, Any]] = {}
    turnover_stats: dict[str, dict[str, Any]] = {}
    for days in windows:
        sample = _window(bars, days)
        if len(bars) > days:
            returns[f"{days}"] = _pct(close, bars[-days - 1].get("close"))
        elif len(sample) >= 2:
            returns[f"{days}"] = _pct(close, sample[0].get("close"))
        closes = [_num(item.get("close")) for item in sample]
        closes = [item for item in closes if item is not None]
        if closes:
            ma = mean(closes)
            moving_average[f"ma{days}"] = {
                "value": round(ma, 4),
                "distance_pct": _pct(close, ma),
                "above": bool(close is not None and close >= ma),
            }
        vol_sample = [_num(item.get("volume")) for item in sample]
        vol_sample = [item for item in vol_sample if item is not None]
        if vol_sample:
            volume_stats[f"{days}d"] = {
                "avg": round(mean(vol_sample), 2),
                "latest_ratio": _ratio(latest.get("volume"), mean(vol_sample)),
            }
        turn_sample = [_num(item.get("turnover_rate")) for item in sample]
        turn_sample = [item for item in turn_sample if item is not None and item > 0]
        if turn_sample:
            turnover_stats[f"{days}d"] = {
                "avg": round(mean(turn_sample), 4),
                "latest_ratio": _ratio(latest.get("turnover_rate"), mean(turn_sample)),
            }

    gap_pct = None
    if len(bars) >= 2:
        gap_pct = _pct(latest.get("open"), bars[-2].get("close"))

    latest_change_pct = _pct(latest.get("close"), bars[-2].get("close")) if len(bars) >= 2 else None
    amplitudes: list[float] = []
    for item in _window(bars, 20):
        high = _num(item.get("high"))
        low = _num(item.get("low"))
        prev = _num(item.get("close"))
        if high is not None and low is not None and prev not in (None, 0):
            amplitudes.append((high - low) / prev * 100)

    recent = []
    for item in bars[-keep_recent:]:
        recent.append({
            "date": item.get("date"),
            "open": item.get("open"),
            "high": item.get("high"),
            "low": item.get("low"),
            "close": item.get("close"),
            "volume": item.get("volume"),
            "amount": item.get("amount"),
            "turnover_rate": item.get("turnover_rate"),
        })

    return {
        "period": period,
        "count": len(bars),
        "date_range": {"start": bars[0].get("date"), "end": latest.get("date")},
        "latest": {
            "date": latest.get("date"),
            "open": latest.get("open"),
            "high": latest.get("high"),
            "low": latest.get("low"),
            "close": latest.get("close"),
            "change_pct": latest_change_pct,
            "gap_pct": gap_pct,
            "volume": latest.get("volume"),
            "amount": latest.get("amount"),
            "turnover_rate": latest.get("turnover_rate"),
        },
        "returns_pct": {key: value for key, value in returns.items() if value is not None},
        "moving_average": moving_average,
        "volume": {
            **volume_stats,
            "latest_percentile_120": _percentile_rank(volumes[-120:], latest.get("volume")),
        },
        "amount": {
            "avg_20d": round(mean(amounts[-20:]), 2) if amounts else None,
            "latest_ratio_to_20d": _ratio(latest.get("amount"), mean(amounts[-20:])) if amounts else None,
        },
        "turnover_rate": turnover_stats,
        "volatility": {
            "atr14_pct": _atr_pct(bars, 14),
            "avg_amplitude_20d": round(mean(amplitudes), 2) if amplitudes else None,
        },
        "trend": {
            "streak": _trend_streak(bars),
            "support_resistance": _support_resistance(bars, [20, 60, 120, 250]),
        },
        "recent_bars": recent,
    }


def _percentile_rank(values: list[float], value: Any) -> float | None:
    current = _num(value)
    cleaned = [item for item in values if item is not None and isfinite(item)]
    if current is None or not cleaned:
        return None
    below = sum(1 for item in cleaned if item <= current)
    return round(below / len(cleaned), 4)


def _point_time(point: dict[str, Any]) -> str:
    return str(point.get("time_label") or point.get("time") or point.get("timeText") or "")


def _point_price(point: dict[str, Any]) -> float | None:
    return _round(point.get("price") if point.get("price") is not None else point.get("matchPrice"), 4)


def _point_volume(point: dict[str, Any]) -> int | None:
    return _int(point.get("matched_volume") if point.get("matched_volume") is not None else point.get("volume"))


def _point_unmatched(point: dict[str, Any]) -> int | None:
    return _int(point.get("unmatched_volume") if point.get("unmatched_volume") is not None else point.get("unmatchedDelta"))


def _select_key_points(points: list[dict[str, Any]], max_points: int = 9) -> list[list[Any]]:
    if not points:
        return []
    if len(points) <= max_points:
        selected = points
    else:
        anchors = {0, len(points) - 1}
        for ratio in (0.25, 0.5, 0.75):
            anchors.add(min(len(points) - 1, int(len(points) * ratio)))
        anchors.update(range(max(0, len(points) - 4), len(points)))
        selected = [points[index] for index in sorted(anchors)[:max_points]]
    return [[_point_time(point), _point_price(point), _point_volume(point), _point_unmatched(point)] for point in selected]


def _summarize_auction_phase(phase: dict[str, Any], points: list[dict[str, Any]], quote: dict[str, Any]) -> dict[str, Any]:
    prices = [_point_price(point) for point in points]
    prices = [item for item in prices if item is not None]
    volumes = [_point_volume(point) for point in points]
    volumes = [item for item in volumes if item is not None]
    unmatched = [_point_unmatched(point) for point in points]
    unmatched = [item for item in unmatched if item is not None]
    final_points = points[-3:]
    final_prices = [_point_price(point) for point in final_points]
    final_prices = [item for item in final_prices if item is not None]
    final_volumes = [_point_volume(point) for point in final_points]
    final_volumes = [item for item in final_volumes if item is not None]

    final_price_change_pct = None
    if len(final_prices) >= 2:
        final_price_change_pct = _pct(final_prices[-1], final_prices[0])

    final_volume_ratio = None
    if volumes and final_volumes:
        final_volume_ratio = _ratio(sum(final_volumes), sum(volumes))

    raw_volume = phase.get("volume")
    total_hand = quote.get("total_hand")
    return {
        "snapshot": {
            "time": phase.get("time"),
            "price": _round(phase.get("price"), 4),
            "volume": _int(raw_volume),
            "amount": _round(phase.get("amount"), 2),
            "gap_rate": _round(phase.get("gapRate"), 4),
            "auction_volume_ratio": phase.get("auctionVolumeRatio") if phase.get("auctionVolumeRatio") is not None else _ratio(raw_volume, total_hand),
            "unmatched_delta": _int(phase.get("unmatchedDelta")),
            "strength_label": phase.get("strengthLabel"),
            "anchor_exact": phase.get("anchorExact"),
            "data_confidence": phase.get("dataConfidence"),
        },
        "process": {
            "point_count": len(points),
            "price_low": round(min(prices), 4) if prices else None,
            "price_high": round(max(prices), 4) if prices else None,
            "price_spread_pct": _pct(max(prices), min(prices)) if len(prices) >= 2 else None,
            "first_to_last_pct": _pct(prices[-1], prices[0]) if len(prices) >= 2 else None,
            "final_3_point_price_change_pct": final_price_change_pct,
            "final_3_point_volume_ratio": final_volume_ratio,
            "unmatched_median": round(median(unmatched), 2) if unmatched else None,
            "unmatched_latest": unmatched[-1] if unmatched else None,
            "has_late_pull_up": bool(final_price_change_pct is not None and final_price_change_pct >= 0.2),
            "has_late_drop": bool(final_price_change_pct is not None and final_price_change_pct <= -0.2),
            "has_late_volume_concentration": bool(final_volume_ratio is not None and final_volume_ratio >= 0.45),
        },
        "key_points": _select_key_points(points),
    }


def summarize_auction(payload: dict[str, Any]) -> dict[str, Any]:
    details = _safe_dict(payload.get("details"))
    quote = _safe_dict(details.get("quote") or payload.get("quote"))
    opening_points = _safe_list(details.get("openingPoints") or payload.get("openingPoints"))
    closing_points = _safe_list(details.get("closingPoints") or payload.get("closingPoints"))
    auction_0925 = _safe_dict(details.get("auction0925") or payload.get("auction0925"))
    pre_close = quote.get("pre_close_price")
    last_price = quote.get("last_price")
    open_price = quote.get("open_price")
    return {
        "trade_date": payload.get("trade_date"),
        "quote": {
            "symbol": quote.get("code") or payload.get("symbol"),
            "name": quote.get("name"),
            "last_price": _round(last_price, 4),
            "pre_close_price": _round(pre_close, 4),
            "open_price": _round(open_price, 4),
            "gap_rate_by_open": _pct(open_price, pre_close),
            "last_change_pct": _pct(last_price, pre_close),
            "total_hand": _int(quote.get("total_hand")),
            "amount": _round(quote.get("amount"), 2),
            "inside_dish": _int(quote.get("inside_dish")),
            "outer_disc": _int(quote.get("outer_disc")),
        },
        "auction_0925": {
            "has_auction_0925": bool(auction_0925.get("has_auction_0925")),
            "price": _round(auction_0925.get("price"), 4),
            "volume": _int(auction_0925.get("volume")),
            "amount": _round(auction_0925.get("amount"), 2),
            "gap_rate": _pct(auction_0925.get("price"), pre_close),
        },
        "opening": _summarize_auction_phase(_safe_dict(payload.get("opening")), opening_points, quote),
        "closing": _summarize_auction_phase(_safe_dict(payload.get("closing")), closing_points, quote),
    }


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    data = _safe_dict(payload)
    rows = data.get("rows")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    sections = data.get("sections")
    if isinstance(sections, dict):
        out: list[dict[str, Any]] = []
        for value in sections.values():
            if isinstance(value, list):
                out.extend([row for row in value if isinstance(row, dict)])
        return out
    return []


def _compact_rows(rows: list[dict[str, Any]], limit: int = 8, max_keys: int = 10) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows[:limit]:
        compact: dict[str, Any] = {}
        for key, value in row.items():
            if value in (None, "", [], {}):
                continue
            compact[str(key)] = _round(value, 4) if isinstance(value, (int, float)) else value
            if len(compact) >= max_keys:
                break
        if compact:
            out.append(compact)
    return out


def _summarize_topics(payload: dict[str, Any]) -> dict[str, Any]:
    topics = _safe_list(payload.get("topics") or payload.get("hot_topics"))
    valid = []
    for item in topics:
        if not isinstance(item, dict):
            continue
        name = str(item.get("topic_name") or item.get("name") or "").strip()
        topic_id = str(item.get("topic_id") or "").strip()
        if not name and not topic_id:
            continue
        valid.append({
            "topic_id": topic_id or None,
            "topic_name": name or None,
            "relation_level": item.get("relation_level"),
            "reason": item.get("reason"),
        })
    details = _safe_list(payload.get("topic_details"))
    return {
        "count": payload.get("count") or len(valid),
        "items": valid[:12],
        "detail_count": len(details),
    }


def summarize_fundamentals(bundle: dict[str, Any]) -> dict[str, Any]:
    if not bundle:
        return {"available": False}
    stock_info = _safe_dict(bundle.get("stock_info"))
    turnover = _safe_dict(stock_info.get("turnover"))
    turnover_latest = _safe_dict(turnover.get("latest"))
    raw_info = _safe_dict(stock_info.get("raw"))
    return {
        "available": True,
        "stock_info": {
            "raw_excerpt": _compact_rows([raw_info], limit=1, max_keys=14)[0] if raw_info else {},
            "circulating_shares": _round(turnover.get("circulating_shares"), 2),
            "total_shares": _round(turnover.get("total_shares"), 2),
            "latest_turnover_rate": _round(turnover_latest.get("turnover_rate"), 4),
        },
        "topics": _summarize_topics(_safe_dict(bundle.get("topics"))),
        "business_composition": {
            "report_date": _safe_dict(bundle.get("business_composition")).get("report_date"),
            "top_rows": _compact_rows(_extract_rows(bundle.get("business_composition")), limit=8),
        },
        "valuation": {
            "latest_rows": _compact_rows(_extract_rows(bundle.get("valuation")), limit=8),
        },
        "profit_forecast": {
            "latest_rows": _compact_rows(_extract_rows(bundle.get("profit_forecast")), limit=8),
        },
        "finance": {
            "balance_rows": _compact_rows(_extract_rows(bundle.get("finance_report_balance")), limit=6),
            "income_rows": _compact_rows(_extract_rows(bundle.get("finance_report_income")), limit=6),
            "cashflow_rows": _compact_rows(_extract_rows(bundle.get("finance_report_cashflow")), limit=6),
            "diagnosis_profit": _compact_rows(_extract_rows(bundle.get("finance_diagnosis_profit")), limit=6),
            "diagnosis_growth": _compact_rows(_extract_rows(bundle.get("finance_diagnosis_growth")), limit=6),
            "diagnosis_cashflow": _compact_rows(_extract_rows(bundle.get("finance_diagnosis_cashflow")), limit=6),
        },
        "score": {
            "rows": _compact_rows(_extract_rows(bundle.get("stock_score")), limit=8),
        },
        "ranking": {
            "rows": _compact_rows(_extract_rows(bundle.get("ranking_detail")), limit=8),
        },
        "governance": {
            "risk_rows": _compact_rows(_extract_rows(bundle.get("governance")), limit=8),
        },
        "theme_market": {
            "rows": _compact_rows(_extract_rows(bundle.get("theme_market")), limit=10),
        },
    }


def summarize_breadth(latest: dict[str, Any], series: list[dict[str, Any]]) -> dict[str, Any]:
    clean_series = [item for item in series if isinstance(item, dict)]
    recent = clean_series[-20:]
    latest_payload = latest or (clean_series[-1] if clean_series else {})
    up_count = _num(latest_payload.get("upCount"))
    down_count = _num(latest_payload.get("downCount"))
    total = _num(latest_payload.get("totalCount")) or ((up_count or 0) + (down_count or 0))
    up_ratio = round(up_count / total, 4) if up_count is not None and total else None

    limit_counts = [_num(item.get("limitUpCount")) for item in recent]
    limit_counts = [item for item in limit_counts if item is not None]
    down_counts = [_num(item.get("limitDownCount")) for item in recent]
    down_counts = [item for item in down_counts if item is not None]
    return {
        "latest": {
            "date": latest_payload.get("date"),
            "up_count": _int(latest_payload.get("upCount")),
            "down_count": _int(latest_payload.get("downCount")),
            "up_ratio": up_ratio,
            "limit_up_count": _int(latest_payload.get("limitUpCount")),
            "limit_down_count": _int(latest_payload.get("limitDownCount")),
            "break_rate": _round(latest_payload.get("breakRate"), 4),
            "max_lianban": _int(latest_payload.get("maxLianBan")),
            "total_turnover": _round(latest_payload.get("totalTurnover"), 2),
        },
        "recent_20d": {
            "limit_up_avg": round(mean(limit_counts), 2) if limit_counts else None,
            "limit_up_latest_percentile": _percentile_rank(limit_counts, latest_payload.get("limitUpCount")),
            "limit_down_avg": round(mean(down_counts), 2) if down_counts else None,
            "limit_down_latest_percentile": _percentile_rank(down_counts, latest_payload.get("limitDownCount")),
        },
        "recent_points": _compact_rows(recent[-10:], limit=10, max_keys=8),
    }


def summarize_sector_market(payload: dict[str, Any], *, limit: int = 12) -> dict[str, Any]:
    items = _safe_list(payload.get("items"))
    compact: list[dict[str, Any]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        compact.append({
            "rank": item.get("rank"),
            "code": item.get("full_code") or item.get("code"),
            "name": item.get("name"),
            "change_pct": _round(item.get("change_pct") or item.get("涨幅"), 4),
            "amount": _round(item.get("amount") or item.get("成交额"), 2),
            "open_pct": _round(item.get("open_pct"), 4),
            "amplitude_pct": _round(item.get("amplitude_pct"), 4),
            "entrust_ratio": _round(item.get("entrust_ratio"), 4),
        })
    return {
        "category": payload.get("category"),
        "sort_by": payload.get("sort_by"),
        "total": payload.get("total"),
        "top_items": compact,
    }


def _collect_sources(**results: ReadResult) -> dict[str, Any]:
    return {key: result.to_source_meta() for key, result in results.items()}


def _json_len(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _trim_to_budget(payload: dict[str, Any], max_chars: int) -> dict[str, Any]:
    payload.setdefault("input_budget", {})
    payload["input_budget"]["max_chars"] = max_chars
    payload["input_budget"]["estimated_chars_before_trim"] = _json_len(payload)
    if _json_len(payload) <= max_chars:
        payload["input_budget"]["estimated_chars"] = _json_len(payload)
        payload["input_budget"]["trimmed"] = False
        return payload

    trim_steps = [
        ("technical.daily.recent_bars", []),
        ("technical.weekly.recent_bars", []),
        ("technical.minute_5.recent_bars", []),
        ("market.breadth.recent_points", []),
        ("industry.industry_market.top_items", []),
        ("industry.concept_market.top_items", []),
        ("fundamentals.theme_market.rows", []),
        ("fundamentals.finance.balance_rows", []),
        ("fundamentals.finance.income_rows", []),
        ("fundamentals.finance.cashflow_rows", []),
        ("fundamentals.governance.risk_rows", []),
    ]
    for path, replacement in trim_steps:
        cursor: Any = payload
        parts = path.split(".")
        for part in parts[:-1]:
            cursor = cursor.get(part) if isinstance(cursor, dict) else None
            if cursor is None:
                break
        if isinstance(cursor, dict) and parts[-1] in cursor:
            cursor[parts[-1]] = replacement
        if _json_len(payload) <= max_chars:
            break
    payload["input_budget"]["estimated_chars"] = _json_len(payload)
    payload["input_budget"]["trimmed"] = True
    if _json_len(payload) > max_chars:
        payload.setdefault("data_quality", {}).setdefault("warnings", []).append("feature summary still exceeds max_chars after trim")
    return payload


def build_stock_feature_summary(
    *,
    target_type: str,
    symbol: str,
    name: str | None = None,
    adjust: str = "qfq",
    max_chars: int = DEFAULT_MAX_INPUT_CHARS,
    reader: StockAnalysisDataReader | None = None,
) -> dict[str, Any]:
    reader = reader or create_default_stock_analysis_data_reader()
    max_chars = max(20_000, int(max_chars or DEFAULT_MAX_INPUT_CHARS))

    auction_result = reader.read_auction(symbol)
    daily_result = reader.read_klines(target_type, symbol, "1d", adjust)
    weekly_result = reader.read_klines(target_type, symbol, "1w", adjust)
    minute5_result = reader.read_klines(target_type, symbol, "5m", adjust)
    turnover_result = reader.read_turnover(target_type, symbol)
    breadth_latest_result = reader.read_breadth_latest()
    breadth_series_result = reader.read_breadth_series(limit=180)
    meta_result = reader.read_stock_meta(target_type, symbol)
    fundamentals_result = reader.read_fundamentals_bundle(symbol, target_type=target_type)
    industry_market_result = reader.read_sector_market("行业指数", count=80)
    concept_market_result = reader.read_sector_market("概念指数", count=80)

    warnings: list[str] = []
    for result in [
        auction_result,
        daily_result,
        weekly_result,
        minute5_result,
        turnover_result,
        breadth_latest_result,
        breadth_series_result,
        meta_result,
        fundamentals_result,
        industry_market_result,
        concept_market_result,
    ]:
        warnings.extend(result.warnings)

    meta = _safe_dict(meta_result.data)
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now().isoformat(),
        "target": {
            "target_type": target_type,
            "symbol": symbol,
            "name": name or meta.get("name") or symbol,
            "adjust": adjust,
            "cap_style": meta.get("capStyle"),
            "sector_index_symbol": meta.get("sectorIndexSymbol"),
            "sector_index_name": meta.get("sectorIndexName"),
        },
        "auction": summarize_auction(_safe_dict(auction_result.data)),
        "technical": {
            "daily": summarize_bars(_safe_list(daily_result.data), period="1d", keep_recent=16),
            "weekly": summarize_bars(_safe_list(weekly_result.data), period="1w", keep_recent=12),
            "minute_5": summarize_bars(_safe_list(minute5_result.data), period="5m", keep_recent=18),
        },
        "turnover": {
            "available": bool(turnover_result.data),
            "circulating_shares": _round(_safe_dict(turnover_result.data).get("circulating_shares"), 2),
            "total_shares": _round(_safe_dict(turnover_result.data).get("total_shares"), 2),
            "latest": _safe_list(_safe_dict(turnover_result.data).get("entries"))[-1] if _safe_list(_safe_dict(turnover_result.data).get("entries")) else None,
        },
        "fundamentals": summarize_fundamentals(_safe_dict(fundamentals_result.data)),
        "industry": {
            "meta": {
                "sector_index_symbol": meta.get("sectorIndexSymbol"),
                "sector_index_name": meta.get("sectorIndexName"),
                "industry": meta.get("industry"),
                "concept": meta.get("concept"),
            },
            "industry_market": summarize_sector_market(_safe_dict(industry_market_result.data)),
            "concept_market": summarize_sector_market(_safe_dict(concept_market_result.data)),
        },
        "market": {
            "breadth": summarize_breadth(_safe_dict(breadth_latest_result.data), _safe_list(breadth_series_result.data)),
        },
        "ai_usage_guidance": {
            "role": "Use this compressed feature summary as primary evidence. Treat source warnings as uncertainty, and avoid absolute buy/sell instructions.",
            "focus": [
                "auction strength and validity",
                "price-volume trend alignment",
                "turnover and liquidity abnormality",
                "market breadth and sector resonance",
                "fundamental or governance risk that may invalidate short-term signals",
            ],
        },
        "data_quality": {
            "warnings": [item for item in warnings if item],
        },
        "_sources": _collect_sources(
            auction=auction_result,
            daily=daily_result,
            weekly=weekly_result,
            minute5=minute5_result,
            turnover=turnover_result,
            breadth_latest=breadth_latest_result,
            breadth_series=breadth_series_result,
            stock_meta=meta_result,
            fundamentals=fundamentals_result,
            industry_market=industry_market_result,
            concept_market=concept_market_result,
        ),
    }
    return _trim_to_budget(payload, max_chars)
