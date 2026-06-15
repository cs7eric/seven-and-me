"""涨跌停情绪 (limitEmotion) 服务.

在"市场脉搏"里输出 4 块:
  1) 涨停 / 跌停家数
  2) 盘中触板 / 炸板 / 炸板率
  3) 连板高度 / 梯队 / 晋级率 / 断板反馈
  4) 连板情绪判断

数据源:
  - 实时行情: eltdx list_by_category("沪深A股") 翻 4 个 sort_by 角度 (涨幅升/降 / 成交额),
              配合 universe 的 code→name + is_st + is_new 给每只 quote 补齐元数据.
  - 连板历史: ``reference/market-limit/daily/<prev_trading_date>.json``.

持久化 (不依赖数据库):
  reference/market-pulse/latest.json
  reference/market-pulse/snapshots/<trade_date>/<HHMMSS>.json
  reference/market-limit/daily/<trade_date>.json
  reference/market-limit/config.json

所有写入走原子写 (tmp -> rename). 读盘失败 fallback 到 None, 不抛.

交易日/非交易日行为:
  - 交易日 (含盘内/盘后): 走实时拉取 → 最新行情写 latest.json + snapshot.
  - 非交易日: 不拉实时, 直接读最近一份 ``daily/*.json`` 聚合, 仍写到 latest.json
    (tradeDate 字段反映该交易日), 快照跳过 (避免误判盘中).
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.config.settings import (
    MARKET_LIMIT_CONFIG_FILE,
    MARKET_LIMIT_DAILY_DIR,
    MARKET_PULSE_LIMIT_LATEST_FILE,
    MARKET_PULSE_LIMIT_SNAPSHOTS_DIR,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 内存锁: 防止并发触发 (scheduler + API 同时拉)
# ---------------------------------------------------------------------------
_compute_lock = threading.Lock()
_universe_lock = threading.Lock()
_universe_cache: dict[str, Any] | None = None
_universe_loaded_at: float = 0.0
_UNIVERSE_TTL_SECONDS = 60 * 30  # 30 分钟

# ---------------------------------------------------------------------------
# 默认配置
# ---------------------------------------------------------------------------
DEFAULT_CONFIG: dict[str, Any] = {
    "excludeST": True,
    "excludeNewStock": True,
    "excludeSuspended": True,
    "marketScope": ["SH", "SZ", "BJ"],
    "limitPriceTolerance": 0.0001,
    "highStreakThreshold": 3,
    "staleMinutes": 5,
    "snapshotIntervalMinutes": 30,
}


# ---------------------------------------------------------------------------
# 工具: 阈值 (涨跌停百分比)
# ---------------------------------------------------------------------------
def _threshold_for(full_code: str) -> float:
    """A 股涨跌停阈值 (百分比), 实际容差 = threshold - 0.05.

    - 主板 / 中小板: 10% (用 9.95)
    - 创业板 / 科创板: 20% (用 19.95)
    - 北交所: 30% (用 29.95)

    ST 一律 5% (用 4.95), 与板块无关 — 这跟交易所规则一致:
    ST 股票 (含创业板 ST、科创板 ST、北交所 ST) 涨跌幅都是 5%.

    同时支持带前缀 code (sh600519, sz300xxx, bj920xxx) 和纯 6 位数字 code.
    """
    raw = (full_code or "").lower()
    # 剥掉 sh/sz/bj 前缀，转成 bare 6 位 code
    bare = raw[2:] if raw[:2] in ("sh", "sz", "bj") and len(raw) == 8 else raw
    if bare.startswith(("8", "4", "92")):
        return 29.95
    if bare.startswith(("30", "301", "688", "689")):
        return 19.95
    return 9.95


def _infer_exchange_from_bare_code(code: str) -> str:
    """从 6 位纯 code 推断交易所 (universe meta 缺失时兜底).

    与 ``_threshold_for`` / 上交所深交所北交所规则保持一致:
      - 60xxxx / 601xxx / 603xxx / 605xxx / 688xxx / 689xxx → sh
      - 000xxx / 001xxx / 002xxx / 003xxx / 30xxxx / 301xxx → sz
      - 8xxxxx / 4xxxxx / 92xxxx → bj
      - 其它 (5xxxxx 老基金等不参与) → ""

    实时数据每天会带完整 ``bj920634`` 这类 code, universe meta 通常都有;
    仅在 universe 缺这只股时, 聚合才走这里 (daily 文件里 code 是 6 位无前缀).
    """
    if not code or len(code) != 6 or not code.isdigit():
        return ""
    if code.startswith(("60", "688", "689")):
        return "sh"
    if code.startswith(("00", "30", "301")):
        return "sz"
    if code.startswith(("8", "4", "92")):
        return "bj"
    return ""


def _is_st(name: str | None) -> bool:
    if not name:
        return False
    upper = name.upper()
    return upper.startswith("ST") or upper.startswith("*ST") or "退" in name


def _is_suspended(q: dict[str, Any]) -> bool:
    """停牌识别: 最新价 <= 0 或 pre_close <= 0 都按停牌处理."""
    last = q.get("last_price")
    pre = q.get("pre_close_price")
    try:
        return (last is None or float(last) <= 0) or (pre is None or float(pre) <= 0)
    except (TypeError, ValueError):
        return True


# ---------------------------------------------------------------------------
# 工具: 原子写 / 安全读
# ---------------------------------------------------------------------------
def _write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    tmp.replace(path)


def _read_json_safe(path: Path, default: Any = None) -> Any:
    if not path.exists() or path.stat().st_size == 0:
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("read json failed (%s): %s", path, exc)
        return default


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
def _load_config() -> dict[str, Any]:
    blob = _read_json_safe(MARKET_LIMIT_CONFIG_FILE, default={}) or {}
    out = dict(DEFAULT_CONFIG)
    if isinstance(blob, dict):
        out.update(blob)
    return out


def save_config(config: dict[str, Any]) -> dict[str, Any]:
    merged = dict(DEFAULT_CONFIG)
    if isinstance(config, dict):
        merged.update(config)
    _write_json_atomic(MARKET_LIMIT_CONFIG_FILE, merged)
    return merged


# ---------------------------------------------------------------------------
# Universe: code → {name, is_st, is_new, exchange}
#
# 复用 :func:`market_heatmap_service._load_name_map` 的思路, 但
# 顺手把 universe topics 里的 "ST板块" / "次新股" 也抽出来, 减少对外部库的依赖.
# ---------------------------------------------------------------------------
def _load_universe_meta(refresh: bool = False) -> dict[str, dict[str, Any]]:
    """返回 code (full_code, e.g. sh600519) -> {name, is_st, is_new, exchange}.

    key 归一: universe 里 6 位 code (920634) 和 realtime 的 full_code (bj920634)
    都映射到同一个 meta entry, 实际存放两份 key 都指向同一份 dict.
    """
    import time as _t
    global _universe_cache, _universe_loaded_at
    with _universe_lock:
        if (not refresh
            and _universe_cache is not None
            and (_t.time() - _universe_loaded_at) < _UNIVERSE_TTL_SECONDS):
            return _universe_cache

        meta: dict[str, dict[str, Any]] = {}

        def _put(code: str, name: str, is_st: bool, is_new: bool, exchange: str) -> None:
            if not code:
                return
            entry = {
                "name": name,
                "is_st": is_st,
                "is_new": is_new,
                "exchange": exchange,
            }
            # 同时存 6 位 + full_code 两种 key
            bare = code[2:] if code[:2] in ("sh", "sz", "bj") and len(code) == 8 else code
            meta[code] = entry
            if bare != code:
                meta[bare] = entry

        # 1) 优先 load_latest() (有 topics, 能判 ST / 新股)
        try:
            from .stock_universe_service import load_latest
            blob = load_latest() or {}
        except Exception as exc:
            logger.debug("universe load_latest failed: %s", exc)
            blob = {}
        for s in (blob.get("stocks") or []):
            code = str(s.get("code") or "").strip()
            if not code:
                continue
            full = code.lower()
            name = (s.get("name") or "").strip()
            topic_names = [t.get("topic_name") for t in (s.get("topics") or [])]
            is_st = bool(name and _is_st(name)) or any(
                t == "ST板块" for t in topic_names
            )
            is_new = any(
                t in ("次新股", "次新超跌") for t in topic_names
            )
            exchange = full[:2] if full[:2] in ("sh", "sz", "bj") else ""
            _put(full, name, is_st, is_new, exchange)

        # 2) 兜底 _codes.json (补 name)
        try:
            from backend.config.settings import STOCK_UNIVERSE_DIR
            codes_file = STOCK_UNIVERSE_DIR / "_codes.json"
            if codes_file.exists():
                blob2 = json.loads(codes_file.read_text(encoding="utf-8"))
                for c in blob2.get("codes") or []:
                    fc = (c.get("full_code") or c.get("code") or "").lower()
                    n = (c.get("name") or "").strip()
                    if not fc or not n:
                        continue
                    if fc in meta and meta[fc].get("name"):
                        continue
                    is_st = _is_st(n) or (meta.get(fc, {}).get("is_st", False))
                    is_new = meta.get(fc, {}).get("is_new", False)
                    ex = (c.get("exchange") or fc[:2]).lower()
                    _put(fc, n, is_st, is_new, ex)
        except Exception as exc:
            logger.debug("universe _codes.json fallback failed: %s", exc)

        _universe_cache = meta
        _universe_loaded_at = _t.time()
        logger.info("universe meta loaded: %d entries", len(meta))
        return meta


# ---------------------------------------------------------------------------
# 实时行情: eltdx list_by_category("沪深A股")
# ---------------------------------------------------------------------------
def _beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


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


def _fetch_realtime_quotes() -> tuple[list[dict[str, Any]], str | None, str | None]:
    """拉沪深 A 股实时行情, 多个 sort_by 角度去重, 补齐 universe 元数据.

    返回 (quotes, source, error).
    """
    try:
        from .f10.service import get_fundamentals_service
    except Exception as exc:
        return [], None, f"f10 service unavailable: {exc}"

    svc = get_fundamentals_service()
    if svc is None:
        return [], None, "fundamentals service is None"

    quotes: list[dict[str, Any]] = []
    seen: set[str] = set()
    page_size = 80
    jobs = [
        {"sort_by": "涨幅", "ascending": False},
        {"sort_by": "涨幅", "ascending": True},
        {"sort_by": "成交额", "ascending": False},
    ]

    try:
        for job in jobs:
            start = 0
            for _ in range(80):  # 最多 80 页 = 6400 只
                try:
                    payload = svc.list_sectors_market(
                        category="沪深A股", sort_by=job["sort_by"],
                        ascending=job["ascending"],
                        start=start, count=page_size,
                    )
                except Exception as exc:
                    logger.debug("list_sectors_market page %d failed: %s", start, exc)
                    break
                items = payload.get("items") or []
                if not items:
                    break
                for raw in items:
                    code = str(raw.get("code") or raw.get("full_code") or "").strip().lower()
                    if not code or code in seen:
                        continue
                    seen.add(code)
                    quotes.append({
                        "code": code,
                        "name": str(raw.get("name") or "").strip(),
                        "last_price": _to_float(raw.get("last_price")),
                        "pre_close_price": _to_float(raw.get("pre_close_price")),
                        "change_pct": _to_float(raw.get("change_pct")),
                        "high_price": _to_float(raw.get("high_price") or raw.get("high")),
                        "low_price": _to_float(raw.get("low_price") or raw.get("low")),
                        "amount": _to_float(raw.get("amount")) or 0.0,
                        "exchange": str(raw.get("exchange") or "").lower(),
                    })
                if len(items) < page_size:
                    break
                start += page_size
    except Exception as exc:
        return quotes, None, f"unexpected: {exc}"

    # 补 universe 元数据
    meta = _load_universe_meta()
    for q in quotes:
        m = meta.get(q["code"]) or {}
        if not q.get("name") and m.get("name"):
            q["name"] = m["name"]
        q["is_st"] = bool(_is_st(q.get("name")) or m.get("is_st", False))
        q["is_new"] = bool(m.get("is_new", False))
        if not q.get("exchange"):
            q["exchange"] = m.get("exchange") or q["code"][:2]
        if not q.get("name"):
            q["name"] = q["code"][-6:]  # 兜底显示 6 位 code
        # 用 last / pre_close 二次补 change_pct
        if q.get("change_pct") in (None, 0):
            last = q.get("last_price")
            pre = q.get("pre_close_price")
            if last and pre and pre > 0:
                q["change_pct"] = round((last - pre) / pre * 100.0, 4)
        q["is_suspended"] = _is_suspended(q)
        if q.get("high_price") is None:
            q["high_price"] = q.get("last_price")
    return quotes, "eltdx.list_by_category(6)+universe", None


# ---------------------------------------------------------------------------
# 1. 涨跌停 / 触板 / 炸板
# ---------------------------------------------------------------------------
def _apply_filters(quotes: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for q in quotes:
        if not q.get("code"):
            continue
        if config.get("excludeSuspended", True) and q.get("is_suspended"):
            continue
        if config.get("excludeST", True) and q.get("is_st"):
            continue
        if config.get("excludeNewStock", True) and q.get("is_new"):
            continue
        scope = set(str(s).lower() for s in (config.get("marketScope") or ["SH", "SZ", "BJ"]))
        ex = (q.get("exchange") or q.get("code", "")[:2]).lower()
        if scope and ex and ex not in scope:
            continue
        out.append(q)
    return out


def _limit_up_down_for_one(
    q: dict[str, Any], tolerance: float
) -> tuple[bool, bool, float | None, float | None]:
    """单只股票: 返回 (is_limit_up, is_limit_down, limit_up_price, limit_down_price).

    阈值表:
      - 主板 / 中小板: ±10% (容差 9.95%)
      - 创业板 / 科创板: ±20% (容差 19.95%)
      - 北交所: ±30% (容差 29.95%)
      - 任何板块的 ST/*ST: ±5% (容差 4.95%)

    判定: last >= limitUpPrice * (1 - tolerance) 算涨停;
          last <= limitDownPrice * (1 + tolerance) 算跌停.
    """
    pre = q.get("pre_close_price")
    if not pre or pre <= 0:
        return False, False, None, None
    full = q.get("code") or ""
    base = 4.95 if q.get("is_st") else _threshold_for(full)
    limit_up_price = round(pre * (1 + base / 100.0), 4)
    limit_down_price = round(pre * (1 - base / 100.0), 4)
    last = q.get("last_price")
    if last is None or last <= 0:
        return False, False, limit_up_price, limit_down_price
    is_up = last >= limit_up_price * (1 - tolerance)
    is_down = last <= limit_down_price * (1 + tolerance)
    return is_up, is_down, limit_up_price, limit_down_price


def calculate_limit_stats(
    quotes: list[dict[str, Any]], config: dict[str, Any]
) -> dict[str, Any]:
    """汇总涨停 / 跌停 / 触板 / 炸板.

    返回:
      {
        limitUp:   {count, stocks: [{code, name, changePct, limitUpPrice}]},
        limitDown: {count, stocks: [{code, name, changePct, limitDownPrice}]},
        breakBoard:{touchedCount, brokenCount, rate, status, label}
      }
    """
    tolerance = float(config.get("limitPriceTolerance") or 0.0001)

    limit_up_stocks: list[dict[str, Any]] = []
    limit_down_stocks: list[dict[str, Any]] = []
    touched_stocks: list[dict[str, Any]] = []

    for q in quotes:
        is_up, is_down, up_price, down_price = _limit_up_down_for_one(q, tolerance)
        cp = q.get("change_pct")
        if is_up:
            limit_up_stocks.append({
                "code": q.get("code"),
                "name": q.get("name") or "",
                "changePct": cp,
                "limitUpPrice": up_price,
            })
        if is_down:
            limit_down_stocks.append({
                "code": q.get("code"),
                "name": q.get("name") or "",
                "changePct": cp,
                "limitDownPrice": down_price,
            })
        high = q.get("high_price")
        if high and up_price and high >= up_price * (1 - tolerance):
            touched_stocks.append({
                "code": q.get("code"),
                "name": q.get("name") or "",
                "highPrice": high,
                "limitUpPrice": up_price,
                "isLimitUpNow": is_up,
            })

    touched_count = len(touched_stocks)
    broken_stocks = [t for t in touched_stocks if not t.get("isLimitUpNow")]
    broken_count = len(broken_stocks)
    rate = round(broken_count / touched_count, 4) if touched_count > 0 else None
    status = "ready" if touched_count > 0 else "unavailable"

    return {
        "limitUp": {
            "count": len(limit_up_stocks),
            "stocks": limit_up_stocks,
        },
        "limitDown": {
            "count": len(limit_down_stocks),
            "stocks": limit_down_stocks,
        },
        "breakBoard": {
            "touchedCount": touched_count,
            "brokenCount": broken_count,
            "rate": rate,
            "status": status,
            "brokenStocks": [{"code": b["code"], "name": b.get("name") or ""} for b in broken_stocks[:20]],
        },
    }


# ---------------------------------------------------------------------------
# 2. 连板体系
# ---------------------------------------------------------------------------
def _build_yesterday_map(prev_payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """从 reference/market-limit/daily/<prev>.json 抽出 code → {limitUpStreak, name}."""
    out: dict[str, dict[str, Any]] = {}
    if not prev_payload or not isinstance(prev_payload.get("stocks"), list):
        return out
    for s in prev_payload["stocks"]:
        if not isinstance(s, dict):
            continue
        c = str(s.get("code") or "").strip().lower()
        if not c:
            continue
        out[c] = {
            "limitUpStreak": int(s.get("limitUpStreak") or 0),
            "name": s.get("name") or "",
        }
    return out


def _calculate_today_streaks(
    quotes: list[dict[str, Any]],
    yesterday_map: dict[str, dict[str, Any]],
    tolerance: float,
) -> list[dict[str, Any]]:
    """给每只股票算 isLimitUp / previousLimitUpStreak / limitUpStreak / isPromoted / isBrokenStreak."""
    rows: list[dict[str, Any]] = []
    for q in quotes:
        is_up, _is_down, up_price, down_price = _limit_up_down_for_one(q, tolerance)
        code = (q.get("code") or "").lower()
        prev = yesterday_map.get(code) or {}
        prev_streak = int(prev.get("limitUpStreak") or 0)
        cur_streak = (prev_streak + 1) if is_up else 0
        name = q.get("name") or prev.get("name") or code[-6:]
        rows.append({
            "code": code,
            "name": name,
            "latestPrice": q.get("last_price"),
            "highPrice": q.get("high_price"),
            "limitUpPrice": up_price,
            "limitDownPrice": down_price,
            "changePct": q.get("change_pct"),
            "isLimitUp": is_up,
            "isTouchedLimitUp": bool(
                q.get("high_price") and up_price
                and q["high_price"] >= up_price * (1 - tolerance)
            ),
            "isBrokenLimitUp": False,
            "previousLimitUpStreak": prev_streak,
            "limitUpStreak": cur_streak,
            "isPromoted": bool(is_up and prev_streak > 0 and cur_streak == prev_streak + 1),
            "isBrokenStreak": bool((not is_up) and prev_streak > 0),
        })
    for r in rows:
        r["isBrokenLimitUp"] = bool(r["isTouchedLimitUp"] and not r["isLimitUp"])
    return rows


def calculate_streak(
    today_rows: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    """计算连板梯队 / 晋级率 / 断板反馈 / 最高连板 / Leaders."""
    high_threshold = int(config.get("highStreakThreshold") or 3)

    # 1. 最高连板 + leaders
    max_height = 0
    for r in today_rows:
        if r.get("limitUpStreak", 0) > max_height:
            max_height = r["limitUpStreak"]
    max_height_out: int | None = max_height if max_height > 0 else None
    leaders: list[dict[str, Any]] = []
    if max_height_out:
        for r in today_rows:
            if r.get("limitUpStreak") == max_height_out:
                leaders.append({
                    "code": r.get("code"),
                    "name": r.get("name") or "",
                    "streak": r.get("limitUpStreak"),
                })

    # 2. 梯队分布 — 每板都带完整 stock list, 不仅是顶部梯队
    bucket: dict[int, list[dict[str, Any]]] = {}
    for r in today_rows:
        s = r.get("limitUpStreak") or 0
        if s <= 0:
            continue
        bucket.setdefault(s, []).append(r)
    distribution = []
    for streak in sorted(bucket.keys(), reverse=True):
        members = bucket[streak]
        stocks = [
            _enrich_stock(
                (m.get("code") or "").lower(),
                m.get("name") or "",
                m.get("changePct"),
                limitUpPrice=m.get("limitUpPrice"),
                limitDownPrice=m.get("limitDownPrice"),
            )
            for m in members
        ]
        distribution.append({
            "streak": streak,
            "count": len(members),
            "stocks": stocks,
        })

    # 3. 晋级率
    yesterday_level_count: dict[int, int] = {}
    for r in today_rows:
        prev = r.get("previousLimitUpStreak") or 0
        if prev > 0:
            yesterday_level_count[prev] = yesterday_level_count.get(prev, 0) + 1
    today_promoted_count: dict[int, int] = {}
    for r in today_rows:
        if r.get("isPromoted"):
            frm = r.get("previousLimitUpStreak") or 0
            today_promoted_count[frm] = today_promoted_count.get(frm, 0) + 1
    levels: list[dict[str, Any]] = []
    for frm in sorted(yesterday_level_count.keys()):
        if frm <= 0:
            continue
        yc = yesterday_level_count[frm]
        tc = today_promoted_count.get(frm, 0)
        levels.append({
            "from": frm,
            "to": frm + 1,
            "yesterdayCount": yc,
            "todayPromotedCount": tc,
            "rate": round(tc / yc, 4) if yc > 0 else None,
        })
    total_yesterday_streak = sum(1 for r in today_rows if (r.get("previousLimitUpStreak") or 0) > 0)
    total_promoted = sum(1 for r in today_rows if r.get("isPromoted"))
    overall_rate = (
        round(total_promoted / total_yesterday_streak, 4)
        if total_yesterday_streak > 0 else None
    )

    # 4. 断板反馈
    broken_stocks = [r for r in today_rows if r.get("isBrokenStreak")]
    high_broken = [r for r in broken_stocks if (r.get("previousLimitUpStreak") or 0) >= high_threshold]

    return {
        "maxHeight": max_height_out,
        "leaders": leaders,
        "distribution": distribution,
        "promotion": {
            "overallRate": overall_rate,
            "levels": levels,
        },
        "broken": {
            "count": len(broken_stocks),
            "highStreakBrokenCount": len(high_broken),
            "stocks": [
                {
                    "code": r.get("code"),
                    "name": r.get("name") or "",
                    "previousStreak": r.get("previousLimitUpStreak") or 0,
                    "changePct": r.get("changePct"),
                }
                for r in broken_stocks
            ],
        },
    }


# ---------------------------------------------------------------------------
# 3. 情绪判断 (启发式)
# ---------------------------------------------------------------------------
def calculate_streak_sentiment(
    streak: dict[str, Any],
    break_board: dict[str, Any],
) -> dict[str, str]:
    max_height = streak.get("maxHeight")
    overall = streak.get("promotion", {}).get("overallRate")
    rate = break_board.get("rate")

    level = "normal"
    text = "连板结构正常, 短线情绪中性。"

    if max_height is None:
        level = "ice"
        text = "暂无连板股, 短线接力情绪进入冰点。"
    elif max_height <= 1 and (overall is None or overall < 0.2):
        level = "ice"
        text = "连板高度受限, 晋级率较低, 短线接力情绪偏冰点。"
    elif max_height <= 2 and (overall is None or overall < 0.3):
        level = "weak"
        text = "连板高度偏低, 接力意愿不足, 短线情绪偏弱。"
    elif 3 <= max_height <= 4:
        level = "normal"
        text = "连板高度有所修复, 市场短线情绪处于正常区间。"
    elif 5 <= max_height <= 6 and (overall is None or overall >= 0.35):
        level = "active"
        text = "连板高度打开, 晋级率尚可, 接力情绪偏强。"
    elif max_height >= 7:
        level = "hot"
        text = "高位连板打开, 短线情绪高热, 需关注高位分歧和断板反馈。"
    elif max_height >= 5:
        level = "active"
        text = "连板高度打开, 接力情绪偏强。"

    if rate is not None:
        if max_height and max_height >= 5 and rate >= 0.5:
            text += f" 但炸板率 {rate*100:.1f}% 偏高, 高位分歧明显。"
        elif (max_height is None or max_height <= 1) and rate >= 0.5:
            text += f" 叠加炸板率 {rate*100:.1f}% 偏高, 弱势明显。"

    return {"level": level, "text": text}


# ---------------------------------------------------------------------------
# 4. daily 文件聚合 (非交易日 / 离线复用)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 行业 / 概念: 一次性扫 universe 缓存, 给每只 code 出 {industry, concepts}
# (替代 find_industries_for / find_concepts_for 那两个 O(N) 单股函数)
# ---------------------------------------------------------------------------
_sector_map_cache: dict[str, dict[str, Any]] | None = None


def _build_sector_map() -> dict[str, dict[str, Any]]:
    global _sector_map_cache
    if _sector_map_cache is not None:
        return _sector_map_cache
    out: dict[str, dict[str, Any]] = {}
    try:
        from .stock_universe_service import load_latest
        blob = load_latest() or {}
    except Exception as exc:
        logger.debug("sector map: universe load failed: %s", exc)
        blob = {}
    for s in (blob.get("stocks") or []):
        full = str(s.get("code") or "").strip().lower()
        if not full:
            continue
        industry = (s.get("industry") or "").strip() or None
        concepts: list[str] = []
        for t in (s.get("topics") or []):
            cr = int(t.get("category_raw") or 0)
            if cr == 2:  # 概念板块
                name = (t.get("topic_name") or "").strip()
                if name and name not in concepts:
                    concepts.append(name)
        if not industry and not concepts:
            continue
        entry = {"industry": industry, "concepts": concepts}
        # 同时存全 code + 6 位 bare code 两种 key, 方便 daily 那种无前缀 lookup
        out[full] = entry
        bare = full[2:] if full[:2] in ("sh", "sz", "bj") and len(full) == 8 else full
        if bare != full:
            out[bare] = entry
    _sector_map_cache = out
    logger.info("sector map: %d entries (after dedup)", len(out))
    return out


def _enrich_stock(code: str, name: str, change_pct: Any, **extra: Any) -> dict[str, Any]:
    """统一给单只股附加 industry / concepts, 方便 limitUp/limitDown/streak 输出."""
    sm = _build_sector_map()
    info = sm.get(code) or {}
    out: dict[str, Any] = {
        "code": code,
        "name": name or "",
        "industry": info.get("industry"),
        "concepts": info.get("concepts") or [],
    }
    if change_pct is not None:
        out["changePct"] = change_pct
    out.update(extra)
    return out


def _aggregate_from_daily(payload: dict[str, Any]) -> dict[str, Any]:
    """从一份 daily/<date>.json 聚合 limitEmotion (不依赖实时行情).

    daily 的 stocks 已经记录:
      isLimitUp, isLimitDown, isTouchedLimitUp, isBrokenLimitUp,
      limitUpStreak, previousLimitUpStreak, isPromoted, isBrokenStreak,
      changePct, name
    """
    stocks = payload.get("stocks") or []
    if not stocks:
        return _empty_limit_emotion()

    # 跟实时路径保持一致: 跑一遍 filter
    config = _load_config()
    # 把 daily 的 stock 转成 quote 形状喂给 _apply_filters
    # ST / 新股用 universe meta 二次确认, 避免 daily 里 name 缺失导致漏判
    universe_meta = _load_universe_meta()
    as_quotes: list[dict[str, Any]] = []
    for s in stocks:
        code = (s.get("code") or "").lower()
        meta = universe_meta.get(code) or {}
        name = s.get("name") or meta.get("name") or ""
        as_quotes.append({
            "code": code,
            "name": name,
            "last_price": s.get("latestPrice"),
            "pre_close_price": None,  # 不影响 filter
            "change_pct": s.get("changePct"),
            "high_price": s.get("highPrice"),
            "exchange": (meta.get("exchange") or _infer_exchange_from_bare_code(code)).lower(),
            "is_st": bool(_is_st(name) or meta.get("is_st", False)),
            "is_new": bool(meta.get("is_new", False)),
            "is_suspended": not (s.get("latestPrice") and float(s.get("latestPrice") or 0) > 0),
        })
    filtered = _apply_filters(as_quotes, config)
    keep_codes = {q["code"] for q in filtered}
    stocks = [s for s in stocks if s.get("code") in keep_codes]
    if not stocks:
        return _empty_limit_emotion()

    limit_up = [s for s in stocks if s.get("isLimitUp")]
    limit_down = [s for s in stocks if s.get("isLimitDown")]
    touched = [s for s in stocks if s.get("isTouchedLimitUp")]
    broken = [s for s in stocks if s.get("isBrokenLimitUp")]

    # 把这些 row 包装成 calculate_streak 期望的格式
    today_rows: list[dict[str, Any]] = []
    for s in stocks:
        today_rows.append({
            "code": s.get("code"),
            "name": s.get("name") or "",
            "changePct": s.get("changePct"),
            "isLimitUp": bool(s.get("isLimitUp")),
            "isTouchedLimitUp": bool(s.get("isTouchedLimitUp")),
            "isBrokenLimitUp": bool(s.get("isBrokenLimitUp")),
            "previousLimitUpStreak": int(s.get("previousLimitUpStreak") or 0),
            "limitUpStreak": int(s.get("limitUpStreak") or 0),
            "isPromoted": bool(s.get("isPromoted")),
            "isBrokenStreak": bool(s.get("isBrokenStreak")),
            # 保留价格字段, _enrich_stock 透传到 tooltip footer
            "limitUpPrice": s.get("limitUpPrice"),
            "limitDownPrice": s.get("limitDownPrice"),
        })

    # 计算连板
    streak = calculate_streak(today_rows, config)

    # 计算炸板率
    touched_count = len(touched)
    broken_count = len(broken)
    if touched_count == 0:
        rate = None
        status = "unavailable"
    else:
        rate = round(broken_count / touched_count, 4)
        status = "ready"

    sentiment = calculate_streak_sentiment(streak, {"rate": rate})

    return {
        "limitUp": {
            "count": len(limit_up),
            "label": "涨停",
            "stocks": [
                _enrich_stock(
                    (s.get("code") or "").lower(),
                    s.get("name") or "",
                    s.get("changePct"),
                    limitUpPrice=s.get("limitUpPrice"),
                )
                for s in limit_up
            ],
        },
        "limitDown": {
            "count": len(limit_down),
            "label": "跌停",
            "stocks": [
                _enrich_stock(
                    (s.get("code") or "").lower(),
                    s.get("name") or "",
                    s.get("changePct"),
                    limitDownPrice=s.get("limitDownPrice"),
                )
                for s in limit_down
            ],
        },
        "breakBoard": {
            "touchedCount": touched_count,
            "brokenCount": broken_count,
            "rate": rate,
            "status": status,
            "label": "炸板率",
            "brokenStocks": [
                _enrich_stock(
                    (s.get("code") or "").lower(),
                    s.get("name") or "",
                    None,
                )
                for s in broken[:20]
            ],
        },
        "streak": {
            "maxHeight": streak["maxHeight"],
            "label": "连板高度",
            "leaders": streak["leaders"],
            "distribution": streak["distribution"],
            "promotion": streak["promotion"],
            "broken": streak["broken"],
            "sentiment": sentiment,
        },
        "_meta": {
            "stockCount": len(stocks),
            "source": "reference/market-limit/daily aggregation",
            "previousTradeDate": None,
            "updateTime": _beijing_now().isoformat(timespec="seconds"),
            "dataStatus": "normal",
        },
    }


# ---------------------------------------------------------------------------
# 5. 找最近一个交易日 + 读取 daily
# ---------------------------------------------------------------------------
def _list_daily_files() -> list[Path]:
    if not MARKET_LIMIT_DAILY_DIR.exists():
        return []
    return sorted(MARKET_LIMIT_DAILY_DIR.glob("*.json"), reverse=True)


def _latest_daily_payload() -> dict[str, Any] | None:
    for p in _list_daily_files():
        blob = _read_json_safe(p, default=None)
        if isinstance(blob, dict) and isinstance(blob.get("stocks"), list):
            return blob
    return None


def _previous_trading_day_file(today: date) -> dict[str, Any] | None:
    """读"今天"前一个交易日的 daily (避开今天)."""
    from backend.services.stock.trading_calendar import previous_trading_day
    candidates: list[Path] = []
    try:
        prev = previous_trading_day(today)
        candidates.append(MARKET_LIMIT_DAILY_DIR / f"{prev.isoformat()}.json")
    except Exception:
        pass
    for p in _list_daily_files():
        if p not in candidates:
            candidates.append(p)
    for c in candidates:
        blob = _read_json_safe(c, default=None)
        if blob and isinstance(blob.get("stocks"), list):
            # 排除"今天"自身 (如果今天刚好是交易日, 这里要拿"昨天")
            td = blob.get("tradeDate")
            if td and str(td) == today.isoformat():
                continue
            return blob
    return None


# ---------------------------------------------------------------------------
# 6. 组装
# ---------------------------------------------------------------------------
def _empty_limit_emotion() -> dict[str, Any]:
    return {
        "limitUp": {"count": None, "label": "涨停", "stocks": []},
        "limitDown": {"count": None, "label": "跌停", "stocks": []},
        "breakBoard": {
            "touchedCount": None,
            "brokenCount": None,
            "rate": None,
            "status": "unavailable",
            "label": "炸板率",
            "brokenStocks": [],
        },
        "streak": {
            "maxHeight": None,
            "label": "连板高度",
            "leaders": [],
            "distribution": [],
            "promotion": {"overallRate": None, "levels": []},
            "broken": {"count": 0, "highStreakBrokenCount": 0, "stocks": []},
            "sentiment": {"level": "normal", "text": "暂无数据, 等待行情接入。"},
        },
        "_meta": {
            "stockCount": 0, "source": "empty",
            "previousTradeDate": None,
            "updateTime": _beijing_now().isoformat(timespec="seconds"),
            "dataStatus": "empty",
        },
    }


def _detect_market_status(now: datetime) -> str:
    try:
        from backend.services.stock.trading_calendar import is_trade_time, is_trading_day
        if not is_trading_day(now.date()):
            return "closed"
        if is_trade_time(now):
            return "trading"
        hm = now.hour * 60 + now.minute
        if hm < 9 * 60 + 30:
            return "pre_open"
        return "closed"
    except Exception:
        return "unknown"


def _assemble_from_realtime(
    quotes: list[dict[str, Any]],
    config: dict[str, Any],
    today: date,
    source: str | None,
) -> dict[str, Any]:
    now = _beijing_now()
    filtered = _apply_filters(quotes, config)
    limit_stats = calculate_limit_stats(filtered, config)
    prev_payload = _previous_trading_day_file(today)
    yesterday_map = _build_yesterday_map(prev_payload)
    tolerance = float(config.get("limitPriceTolerance") or 0.0001)
    today_rows = _calculate_today_streaks(filtered, yesterday_map, tolerance)
    streak = calculate_streak(today_rows, config)
    sentiment = calculate_streak_sentiment(streak, limit_stats["breakBoard"])

    return {
        "limitUp": {
            "count": limit_stats["limitUp"]["count"],
            "label": "涨停",
            "stocks": [
                _enrich_stock(
                    (s.get("code") or "").lower(),
                    s.get("name") or "",
                    s.get("changePct"),
                    limitUpPrice=s.get("limitUpPrice"),
                )
                for s in (limit_stats["limitUp"]["stocks"] or [])
            ],
        },
        "limitDown": {
            "count": limit_stats["limitDown"]["count"],
            "label": "跌停",
            "stocks": [
                _enrich_stock(
                    (s.get("code") or "").lower(),
                    s.get("name") or "",
                    s.get("changePct"),
                    limitDownPrice=s.get("limitDownPrice"),
                )
                for s in (limit_stats["limitDown"]["stocks"] or [])
            ],
        },
        "breakBoard": {
            "touchedCount": limit_stats["breakBoard"]["touchedCount"],
            "brokenCount": limit_stats["breakBoard"]["brokenCount"],
            "rate": limit_stats["breakBoard"]["rate"],
            "status": limit_stats["breakBoard"]["status"],
            "label": "炸板率",
            "brokenStocks": [
                _enrich_stock(
                    (s.get("code") or "").lower(),
                    s.get("name") or "",
                    None,
                )
                for s in (limit_stats["breakBoard"]["brokenStocks"] or [])
            ],
        },
        "streak": {
            "maxHeight": streak["maxHeight"],
            "label": "连板高度",
            "leaders": streak["leaders"],
            "distribution": streak["distribution"],
            "promotion": streak["promotion"],
            "broken": streak["broken"],
            "sentiment": sentiment,
        },
        "_meta": {
            "stockCount": len(filtered),
            "source": source or "empty",
            "previousTradeDate": (prev_payload or {}).get("tradeDate"),
            "updateTime": now.isoformat(timespec="seconds"),
            "dataStatus": "normal",
        },
    }


# ---------------------------------------------------------------------------
# 7. 对外 API
# ---------------------------------------------------------------------------
def build_limit_emotion(force: bool = False) -> dict[str, Any]:
    """实时计算 limitEmotion, 落盘.

    - 交易日: 拉实时 → 聚合 → 写 latest.json + snapshot
    - 非交易日: 不拉实时, 直接读最近 daily 聚合 → 写 latest.json (跳过 snapshot)
    - force=True 跳过 stale 缓存
    """
    with _compute_lock:
        now = _beijing_now()
        today = now.date()
        config = _load_config()
        stale_minutes = int(config.get("staleMinutes") or 5)
        market_status = _detect_market_status(now)

        # 1) 非交易日: 直接聚合 daily
        try:
            from backend.services.stock.trading_calendar import is_trading_day
            is_td = is_trading_day(today)
        except Exception:
            is_td = True

        if not is_td:
            daily = _latest_daily_payload()
            if daily:
                payload = _aggregate_from_daily(daily)
                payload["tradeDate"] = daily.get("tradeDate") or today.isoformat()
                payload["updateTime"] = now.isoformat(timespec="seconds")
                payload["marketStatus"] = "closed"
                payload["dataStatus"] = "normal"
                # 写 latest (不写 snapshot, 非交易日不要分时)
                try:
                    _write_json_atomic(MARKET_PULSE_LIMIT_LATEST_FILE, payload)
                except Exception as exc:
                    logger.warning("write market-pulse/latest.json failed: %s", exc)
                return payload
            # daily 也没有 → 当 empty
            payload = _empty_limit_emotion()
            payload["tradeDate"] = today.isoformat()
            payload["updateTime"] = now.isoformat(timespec="seconds")
            payload["marketStatus"] = "closed"
            payload["dataStatus"] = "empty"
            try:
                _write_json_atomic(MARKET_PULSE_LIMIT_LATEST_FILE, payload)
            except Exception as exc:
                logger.warning("write latest (empty) failed: %s", exc)
            return payload

        # 2) 交易日: stale 直接读盘
        if not force:
            latest = _read_json_safe(MARKET_PULSE_LIMIT_LATEST_FILE, default=None)
            if isinstance(latest, dict):
                ts = latest.get("tradeDate")
                ut = (latest.get("updateTime") or "")
                if ts == today.isoformat() and ut:
                    try:
                        u_dt = datetime.fromisoformat(ut)
                        if (now - u_dt).total_seconds() <= stale_minutes * 60:
                            return latest
                    except Exception:
                        pass

        # 3) 拉实时
        quotes, source, err = _fetch_realtime_quotes()
        if not quotes:
            logger.warning("limitEmotion: realtime quotes empty: %s", err)
            payload = _empty_limit_emotion()
            payload["_meta"]["dataStatus"] = "empty"
            payload["_meta"]["error"] = err
        else:
            payload = _assemble_from_realtime(quotes, config, today, source)

        payload["tradeDate"] = today.isoformat()
        payload["updateTime"] = now.isoformat(timespec="seconds")
        payload["marketStatus"] = market_status
        if "dataStatus" not in payload:
            payload["dataStatus"] = payload.get("_meta", {}).get("dataStatus", "normal")

        # 4) 落盘
        try:
            _write_json_atomic(MARKET_PULSE_LIMIT_LATEST_FILE, payload)
        except Exception as exc:
            logger.warning("write market-pulse/latest.json failed: %s", exc)
        try:
            snap_dir = MARKET_PULSE_LIMIT_SNAPSHOTS_DIR / today.isoformat()
            snap_dir.mkdir(parents=True, exist_ok=True)
            snap_path = snap_dir / f"{now.strftime('%H%M%S')}.json"
            _write_json_atomic(snap_path, payload)
        except Exception as exc:
            logger.warning("write market-pulse snapshot failed: %s", exc)
        return payload


def get_limit_emotion() -> dict[str, Any]:
    """对外读盘入口: 优先读 latest.json; 没有或过旧 (staleMinutes) 就重算."""
    config = _load_config()
    stale_minutes = int(config.get("staleMinutes") or 5)
    latest = _read_json_safe(MARKET_PULSE_LIMIT_LATEST_FILE, default=None)
    if isinstance(latest, dict):
        ut = (latest.get("updateTime") or "")
        if ut:
            try:
                u_dt = datetime.fromisoformat(ut)
                if (_beijing_now() - u_dt).total_seconds() <= stale_minutes * 60:
                    return latest
            except Exception:
                pass
    return build_limit_emotion(force=True)


# ---------------------------------------------------------------------------
# 8. 收盘落盘 daily
# ---------------------------------------------------------------------------
def snapshot_today_daily(force: bool = False) -> dict[str, Any] | None:
    """交易日 15:30 之后调用: 落盘当日全量每只股到
    ``reference/market-limit/daily/<date>.json`` (覆盖当日).

    非交易日直接返回 None (供 API 端报 ok=False), 避免把收盘数据写到
    一个非交易日的文件名, 影响次日连板计算的"前一交易日"匹配.
    """
    with _compute_lock:
        now = _beijing_now()
        today = now.date()
        # 非交易日 (周末 / 节假日) 不落盘 daily; force=True 也不允许
        try:
            from backend.services.stock.trading_calendar import is_trading_day
            if not is_trading_day(today):
                logger.info(
                    "snapshot_today_daily skipped: %s is not a trading day", today,
                )
                return None
        except Exception:
            pass

        target = MARKET_LIMIT_DAILY_DIR / f"{today.isoformat()}.json"
        if not force and target.exists():
            try:
                blob = _read_json_safe(target, default=None)
                if isinstance(blob, dict) and blob.get("marketStatus") in ("closed", "trading"):
                    return blob
            except Exception:
                pass

        config = _load_config()
        quotes, source, err = _fetch_realtime_quotes()
        if not quotes:
            logger.warning("snapshot_today_daily: quotes empty: %s", err)
            return None

        filtered = _apply_filters(quotes, config)
        prev_payload = _previous_trading_day_file(today)
        yesterday_map = _build_yesterday_map(prev_payload)
        tolerance = float(config.get("limitPriceTolerance") or 0.0001)
        today_rows = _calculate_today_streaks(filtered, yesterday_map, tolerance)

        out = {
            "tradeDate": today.isoformat(),
            "updateTime": now.isoformat(timespec="seconds"),
            "marketStatus": _detect_market_status(now),
            "stockCount": len(today_rows),
            "source": source or "empty",
            "stocks": today_rows,
        }
        try:
            _write_json_atomic(target, out)
            logger.info("snapshot_today_daily wrote %d stocks to %s", len(today_rows), target)
        except Exception as exc:
            logger.warning("snapshot_today_daily write failed: %s", exc)
        return out


__all__ = [
    "build_limit_emotion",
    "get_limit_emotion",
    "snapshot_today_daily",
    "save_config",
]
