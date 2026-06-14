"""造 1 周 (5 个交易日) 的 limitEmotion 测试数据.

直接写真实格式的 daily/<date>.json, 不走 ``snapshot_today_daily``.
基于 eltdx 实时 universe 选股, 5 天覆盖:
  - 5 种情绪 (normal / active / weak / ice / hot)
  - 多梯队连板 (1-6 板都有)
  - 涨跌停 / 触板 / 炸板 数量变化
  - sh / sz (主板/ChiNext/STAR) / bj 三种 exchange
  - 10% / 20% / 30% 三种阈值
  - 晋级 / 断板 / 触板 / 炸板 都有
  - 跌停用自定义 ``isLimitDown`` 字段 (聚合会读)
"""
from __future__ import annotations

import json
import random
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import backend.services.stock.trading_calendar as tc  # noqa: E402
import backend.services.stock.limit_emotion_service as svc  # noqa: E402
from backend.config.settings import MARKET_LIMIT_DAILY_DIR  # noqa: E402
from backend.services.stock.limit_emotion_service import (  # noqa: E402
    _aggregate_from_daily,
)

SUNDAY = date(2026, 6, 14)
fake_now = datetime(2026, 6, 14, 17, 30, 0)
tc._today = lambda: SUNDAY
tc._today_dt = lambda: fake_now
svc._beijing_now = lambda: fake_now

# ---------------------------------------------------------------------------
# 1) 拉实时 universe, 应用 _apply_filters 拿到候选池
# ---------------------------------------------------------------------------
svc._universe_cache = None
svc._universe_loaded_at = 0.0
quotes, _, _ = svc._fetch_realtime_quotes()
config = svc._load_config()
filtered = svc._apply_filters(quotes, config)
print(f"原始 universe: {len(quotes)}  filter 后候选: {len(filtered)}")

# 按 exchange 分桶
by_ex = {"sh": [], "sz": [], "bj": []}
for q in filtered:
    code = q.get("code", "")
    ex = q.get("exchange", code[:2] if code[:2] in ("sh", "sz", "bj") else "")
    if ex in by_ex:
        by_ex[ex].append(q)
print(f"  sh={len(by_ex['sh'])}  sz={len(by_ex['sz'])}  bj={len(by_ex['bj'])}")


# ---------------------------------------------------------------------------
# 2) 定义 5 天 + 12 个 leaders (跨天 streak 路径)
# ---------------------------------------------------------------------------
DAYS = [
    {"date": date(2026, 6, 8),  "limitUpTotal": 62,  "limitDownTotal": 7,  "touchedTotal": 95,  "brokenTotal": 35, "label": "周一 (正常)"},
    {"date": date(2026, 6, 9),  "limitUpTotal": 88,  "limitDownTotal": 4,  "touchedTotal": 125, "brokenTotal": 40, "label": "周二 (放量)"},
    {"date": date(2026, 6, 10), "limitUpTotal": 45,  "limitDownTotal": 16, "touchedTotal": 80,  "brokenTotal": 42, "label": "周三 (偏弱)"},
    {"date": date(2026, 6, 11), "limitUpTotal": 26,  "limitDownTotal": 38, "touchedTotal": 62,  "brokenTotal": 46, "label": "周四 (冰点)"},
    {"date": date(2026, 6, 12), "limitUpTotal": 120, "limitDownTotal": 5,  "touchedTotal": 168, "brokenTotal": 50, "label": "周五 (高热)"},
]

# 12 个 leaders 的 streak 路径 [Mon, Tue, Wed, Thu, Fri]
# 0 = 当天非涨停 (断板或从未涨停)
# 链路要求: 0 (非涨停) 之后才能从 0/1 重启, N (涨停) 之后只能 N+1 (晋级) 或 0 (断板)
LEADERS_PATH = [
    [3, 4, 0, 0, 0],   # A: 3→4→断
    [3, 4, 0, 0, 0],   # B: 3→4→断
    [2, 3, 0, 0, 0],   # C: 2→3→断
    [2, 3, 0, 0, 0],   # D: 2→3→断
    [1, 2, 0, 0, 0],   # E: 1→2→断
    [1, 2, 0, 0, 0],   # F: 1→2→断
    [0, 1, 2, 0, 0],   # G: 周二新1→周三2→断
    [0, 1, 0, 0, 0],   # H: 周二新1→断
    [0, 0, 1, 0, 0],   # I: 周三新1→断
    [0, 0, 0, 1, 2],   # J: 周四新1→周五2
    [0, 0, 0, 0, 7],   # K: 周五合成 7 (测多梯队)
    [0, 0, 0, 0, 5],   # L: 周五合成 5
]

# 选 12 个候选 (跨 sh/sz/bj, 优先 bj 给 leader K/L 测 30% 阈值)
random.seed(20260614)
leader_codes: list[str] = []

# 4 个 bj leaders (K, L, A, B)
bj_pool = list(by_ex["bj"])
random.shuffle(bj_pool)
for i in [0, 1, 10, 11]:  # A, B, K, L
    leader_codes.append(bj_pool.pop()["code"])

# 4 个 sz ChiNext (G, H, C, F)
sz_chi = [q for q in by_ex["sz"] if q.get("code", "").startswith(("30", "301"))]
random.shuffle(sz_chi)
for i in [6, 7, 2, 5]:  # G, H, C, F
    leader_codes.append(sz_chi.pop()["code"])

# 2 个 sh STAR (D, E)
sh_star = [q for q in by_ex["sh"] if q.get("code", "").startswith(("688", "689"))]
random.shuffle(sh_star)
for i in [3, 4]:  # D, E
    leader_codes.append(sh_star.pop()["code"])

# 2 个 sz 主板 (I, J)
sz_main = [q for q in by_ex["sz"] if not q.get("code", "").startswith(("30", "301"))]
random.shuffle(sz_main)
for i in [8, 9]:  # I, J
    leader_codes.append(sz_main.pop()["code"])

print(f"\n12 个 leader codes:")
for name, path, code in zip(
    ["A","B","C","D","E","F","G","H","I","J","K","L"],
    LEADERS_PATH,
    leader_codes,
):
    print(f"  {name} ({code}) path={path}  ex={code[:2] if code[:2] in ('sh','sz','bj') else '?'}")

# 非 leader 池 (用于随机 1板 / 触板 / 跌停)
non_leader_pool = [q for q in filtered if q["code"] not in leader_codes]
random.shuffle(non_leader_pool)


# ---------------------------------------------------------------------------
# 3) 每天: 拼 daily rows + 落盘
# ---------------------------------------------------------------------------
prev_streak_map: dict[str, dict] = {}  # code → {limitUpStreak, name} from previous day

for day_idx, day_info in enumerate(DAYS):
    d = day_info["date"]
    iso = d.isoformat()
    random.seed(20260614 + day_idx)  # 每一天用不同种子, 让随机选股变化

    # 3.1 确定当天 limit-up set (code → streak)
    limit_up_streaks: dict[str, int] = {}
    for i, (code, path) in enumerate(zip(leader_codes, LEADERS_PATH)):
        streak = path[day_idx]
        if streak > 0:
            limit_up_streaks[code] = streak

    # 用随机股票补 1板 到 target
    needed = day_info["limitUpTotal"] - len(limit_up_streaks)
    for q in non_leader_pool:
        if needed <= 0:
            break
        if q["code"] not in limit_up_streaks:
            limit_up_streaks[q["code"]] = 1
            needed -= 1

    # 3.2 选 touched-but-broken: target broken_total, 从非 limit-up 池里挑
    broken_set: set[str] = set()
    needed_broken = day_info["brokenTotal"]
    for q in non_leader_pool:
        if needed_broken <= 0:
            break
        if q["code"] not in limit_up_streaks:
            broken_set.add(q["code"])
            needed_broken -= 1

    # 3.3 选 limit-down
    limit_down_set: set[str] = set()
    needed_dn = day_info["limitDownTotal"]
    for q in non_leader_pool:
        if needed_dn <= 0:
            break
        if q["code"] not in limit_up_streaks and q["code"] not in broken_set:
            limit_down_set.add(q["code"])
            needed_dn -= 1

    # 3.4 拼 daily rows
    code_to_quote = {q["code"]: q for q in filtered}
    today_rows: list[dict] = []

    for code, q in code_to_quote.items():
        last = q.get("last_price")
        pre = q.get("pre_close_price")
        if not pre or pre <= 0:
            continue
        threshold = 4.95 if q.get("is_st") else svc._threshold_for(code)
        limit_up_price = round(pre * (1 + threshold / 100), 4)
        limit_down_price = round(pre * (1 - threshold / 100), 4)

        is_up = code in limit_up_streaks
        is_down = code in limit_down_set
        is_broken = code in broken_set

        if is_up:
            cur_streak = limit_up_streaks[code]
            last_out = limit_up_price
            high_out = limit_up_price
            change_pct = round(threshold, 4)
            is_touched = True  # 涨停必然触板
        elif is_down:
            cur_streak = 0
            last_out = limit_down_price
            high_out = limit_down_price
            change_pct = round(-threshold, 4)
            is_touched = False
        elif is_broken:
            cur_streak = 0
            # 触板但炸: high = 涨停价, last = 涨停价下方一点 (3-7%)
            high_out = limit_up_price
            drop_pct = random.uniform(2.5, 6.5)
            last_out = round(limit_up_price * (1 - drop_pct / 100), 4)
            change_pct = round((last_out - pre) / pre * 100, 4)
            is_touched = True
        else:
            cur_streak = 0
            last_out = last
            high_out = q.get("high_price", last)
            change_pct = round((last_out - pre) / pre * 100, 4)
            is_touched = False

        prev = prev_streak_map.get(code, {})
        prev_streak = int(prev.get("limitUpStreak") or 0)
        is_promoted = bool(is_up and prev_streak > 0 and cur_streak == prev_streak + 1)
        is_broken_streak = bool((not is_up) and prev_streak > 0)

        today_rows.append({
            "code": code,
            "name": q.get("name") or code[-6:],
            "latestPrice": last_out,
            "highPrice": high_out,
            "limitUpPrice": limit_up_price,
            "limitDownPrice": limit_down_price,
            "changePct": change_pct,
            "isLimitUp": is_up,
            "isLimitDown": is_down,
            "isTouchedLimitUp": is_touched,
            "isBrokenLimitUp": is_broken,
            "previousLimitUpStreak": prev_streak,
            "limitUpStreak": cur_streak,
            "isPromoted": is_promoted,
            "isBrokenStreak": is_broken_streak,
        })

    # 3.5 落盘
    out = {
        "tradeDate": iso,
        "updateTime": fake_now.replace(
            year=d.year, month=d.month, day=d.day, hour=15, minute=30
        ).isoformat(timespec="seconds"),
        "marketStatus": "closed",
        "stockCount": len(today_rows),
        "source": "test-data-generator",
        "stocks": today_rows,
    }
    target = MARKET_LIMIT_DAILY_DIR / f"{iso}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    # 更新 prev_streak_map
    prev_streak_map = {
        r["code"]: {"limitUpStreak": r["limitUpStreak"], "name": r["name"]}
        for r in today_rows
    }

    # 3.6 跑一遍聚合, 自检
    agg = _aggregate_from_daily(out)
    bb = agg.get("breakBoard", {})
    sk = agg.get("streak", {})
    sn = sk.get("sentiment", {})
    dist = sk.get("distribution", [])
    max_h = sk.get("maxHeight")
    promo = sk.get("promotion", {})
    broken = sk.get("broken", {})

    print(
        f"\n--- {iso}  ({day_info['label']}) ---"
        f"\n  涨停={agg['limitUp']['count']}  跌停={agg['limitDown']['count']}  "
        f"触板={bb.get('touchedCount')}  炸板={bb.get('brokenCount')}  炸板率={(bb.get('rate') or 0)*100:.1f}%"
        f"\n  晋级率={promo.get('overallRate')}  断板={broken.get('count')} (高位{broken.get('highStreakBrokenCount')})"
        f"\n  情绪={sn.get('level')}  maxHeight={max_h}"
    )
    print("  连板梯队:")
    for d in dist:
        streak = d["streak"]
        count = d["count"]
        stocks = d.get("stocks") or []
        if not stocks:
            print(f"    {streak}板 ×{count}  (空)")
            continue
        # 折行: 8 只一行
        per_line = 8
        if count <= per_line:
            head = "  ".join(
                f"{s['code']}/{s.get('name') or '?'}" for s in stocks
            )
            print(f"    {streak}板 ×{count}  |  {head}")
        else:
            head = "  ".join(
                f"{s['code']}/{s.get('name') or '?'}" for s in stocks[:per_line]
            )
            tail = "  ".join(
                f"{s['code']}/{s.get('name') or '?'}" for s in stocks[per_line:2*per_line]
            )
            more = count - 2 * per_line
            print(f"    {streak}板 ×{count}  |  {head}")
            print(f"    {'':>9}  |  {tail}" + (f"  ... +{more}" if more > 0 else ""))

    # 炸板/断板细节
    if bb.get("brokenStocks"):
        bsb = bb["brokenStocks"]
        head = "  ".join(f"{s['code']}/{s.get('name') or '?'}" for s in bsb[:6])
        more = len(bsb) - 6
        print(f"  炸板样本: {head}" + (f"  ... +{more}" if more > 0 else ""))
    if broken.get("stocks"):
        bs = broken["stocks"]
        head = "  ".join(
            f"{s['code']}/{s.get('name') or '?'} ({s['previousStreak']}板)" for s in bs[:6]
        )
        more = len(bs) - 6
        print(f"  断板样本: {head}" + (f"  ... +{more}" if more > 0 else ""))


# ---------------------------------------------------------------------------
# 4) 跑最新一天的完整 5 块 (write latest.json)
# ---------------------------------------------------------------------------
latest_file = sorted(MARKET_LIMIT_DAILY_DIR.glob("*.json"))[-1]
latest_payload = json.loads(latest_file.read_text(encoding="utf-8"))
agg = _aggregate_from_daily(latest_payload)
agg["tradeDate"] = latest_payload.get("tradeDate")
agg["updateTime"] = fake_now.isoformat(timespec="seconds")
agg["marketStatus"] = "closed"
agg["dataStatus"] = "normal"

from backend.config.settings import MARKET_PULSE_LIMIT_LATEST_FILE
MARKET_PULSE_LIMIT_LATEST_FILE.parent.mkdir(parents=True, exist_ok=True)
MARKET_PULSE_LIMIT_LATEST_FILE.write_text(
    json.dumps(agg, ensure_ascii=False, indent=2, default=str),
    encoding="utf-8",
)

print()
print("=" * 90)
print(f"已生成 5 天 daily 数据, 最新一天 ({latest_payload['tradeDate']}) 写入 latest.json")
print(f"  {MARKET_LIMIT_DAILY_DIR}/<日期>.json × 5")
print(f"  {MARKET_PULSE_LIMIT_LATEST_FILE}")
print("=" * 90)
