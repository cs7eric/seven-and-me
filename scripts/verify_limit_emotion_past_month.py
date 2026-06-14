"""过去一个月 (~22 个交易日) 的 limitEmotion 时间序列.

今天 2026-06-14 (周日) → 找过去 30 个日历日, 排除周末 + 节假日, 得到交易日列表.
对每个交易日 ``d``:
  1) 把 ``_today`` / ``_beijing_now`` 打补丁成 ``d`` 15:30
  2) 跑 ``snapshot_today_daily(force=True)`` → 写 ``daily/<d>.json``
  3) 切回"周日"模式, 调 ``build_limit_emotion(force=True)`` 读 daily 聚合
  4) 提取 4 块核心指标

按时间正序跑, 这样 ``_previous_trading_day_file`` 拿到的"上一交易日" daily 一定存在,
连板梯队 / 晋级率 / 断板 才能正确累计.

注意: 实时拉到的都是 eltdx 周日返回的"最后已知报价", 不是真历史. 这里只验证
``snapshot → daily → aggregation → latest`` 链路在多日下的累计行为 (连板梯队能否
从首板 1 累计到 N 板, 晋级率/断板/情绪文案是否随 streak 变化).
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import backend.services.stock.trading_calendar as tc  # noqa: E402
import backend.services.stock.limit_emotion_service as svc  # noqa: E402

# ---------------------------------------------------------------------------
# 1) 找过去 30 个日历日里所有交易日
# ---------------------------------------------------------------------------
TODAY = date(2026, 6, 14)
WINDOW = 30  # 天

trading_days: list[date] = []
cur = TODAY - timedelta(days=1)  # 不含今天
while cur >= TODAY - timedelta(days=WINDOW):
    if tc.is_trading_day(cur):
        trading_days.append(cur)
    cur -= timedelta(days=1)
trading_days.reverse()  # 正序: 旧 → 新

print(f"=== 过去 {WINDOW} 个日历日 → {len(trading_days)} 个交易日 ===")
print("交易日列表 (旧→新):")
for d in trading_days:
    print(f"  {d.isoformat()}  ({['周一','周二','周三','周四','周五','周六','周日'][d.weekday()]})")
print()


# ---------------------------------------------------------------------------
# 2) 每天: 写 daily + 读 daily 聚合
# ---------------------------------------------------------------------------
# 进度保存 (避免重复跑)
OUT_FILE = Path("reference/market-limit/past_month_series.json")
if OUT_FILE.exists():
    series = json.loads(OUT_FILE.read_text(encoding="utf-8"))
    done_dates = {s["tradeDate"] for s in series}
    print(f"已存在 {len(series)} 天结果, 跳过: {sorted(done_dates)[:5]}...")
else:
    series = []
    done_dates = set()


def patch_to_day(d: date) -> None:
    fake_now = datetime(d.year, d.month, d.day, 15, 30, 0)
    tc._today = lambda: d  # type: ignore[assignment]
    tc._today_dt = lambda: fake_now  # type: ignore[assignment]
    svc._beijing_now = lambda: fake_now  # type: ignore[assignment]


def patch_to_sunday() -> None:
    sunday = TODAY  # 2026-06-14
    fake_now = datetime(sunday.year, sunday.month, sunday.day, 17, 30, 0)
    tc._today = lambda: sunday  # type: ignore[assignment]
    tc._today_dt = lambda: fake_now  # type: ignore[assignment]
    svc._beijing_now = lambda: fake_now  # type: ignore[assignment]


# universe cache 提前重置, 避免拿到陈旧数据
svc._universe_cache = None
svc._universe_loaded_at = 0.0

for d in trading_days:
    iso = d.isoformat()
    if iso in done_dates:
        continue

    # 2.1 假装今天是 d, 写 daily
    patch_to_day(d)
    snap = svc.snapshot_today_daily(force=True)
    if not snap:
        print(f"  !! {iso}: snapshot 失败, 跳过")
        continue

    # 2.2 直接读刚写好的 daily/<d>.json, 跑 _aggregate_from_daily.
    #     (如果用 build_limit_emotion 它会走"非交易日 → 最新 daily"分支,
    #      拿到的是当前循环外的 latest, 不是这一天的. 这里要的是当天的.)
    from backend.services.stock.limit_emotion_service import _aggregate_from_daily
    from backend.config.settings import MARKET_LIMIT_DAILY_DIR
    daily_path = MARKET_LIMIT_DAILY_DIR / f"{iso}.json"
    daily_payload = svc._read_json_safe(daily_path, default=None)
    if not daily_payload or not isinstance(daily_payload.get("stocks"), list):
        print(f"  !! {iso}: daily 文件读不到, 跳过")
        continue
    payload = _aggregate_from_daily(daily_payload)
    payload["tradeDate"] = iso
    payload["marketStatus"] = "closed"

    streak = payload.get("streak", {}) or {}
    bb = payload.get("breakBoard", {}) or {}
    promo = streak.get("promotion", {}) or {}
    broken = streak.get("broken", {}) or {}
    sentiment = streak.get("sentiment", {}) or {}
    lu = payload.get("limitUp", {}) or {}
    ld = payload.get("limitDown", {}) or {}

    row = {
        "tradeDate": iso,
        "stockCount": (payload.get("_meta") or {}).get("stockCount"),
        "limitUp": lu.get("count"),
        "limitDown": ld.get("count"),
        "touched": bb.get("touchedCount"),
        "broken": bb.get("brokenCount"),
        "breakRate": bb.get("rate"),
        "maxHeight": streak.get("maxHeight"),
        "promotionRate": promo.get("overallRate"),
        "brokenCount": broken.get("count"),
        "highBrokenCount": broken.get("highStreakBrokenCount"),
        "sentimentLevel": sentiment.get("level"),
        "leaders": [
            {"code": l.get("code"), "name": l.get("name"), "streak": l.get("streak")}
            for l in (streak.get("leaders") or [])[:3]
        ],
        # 全量梯队: [{streak, count, stocks: [{code, name}]}]
        "distribution": [
            {
                "streak": dist.get("streak"),
                "count": dist.get("count"),
                "stocks": dist.get("stocks") or [],
            }
            for dist in (streak.get("distribution") or [])
        ],
        "dataStatus": payload.get("dataStatus"),
    }
    series.append(row)
    print(
        f"  {iso}  涨停={row['limitUp']:>4}  跌停={row['limitDown']:>3}  "
        f"连板={row['maxHeight']}  晋级={row['promotionRate']}  "
        f"断板={row['brokenCount']}  炸板率={row['breakRate']}  "
        f"情绪={row['sentimentLevel']}"
    )


# 还原
patch_to_sunday()
OUT_FILE.write_text(
    json.dumps(series, ensure_ascii=False, indent=2, default=str),
    encoding="utf-8",
)
print()
print(f"=== 已写入 {OUT_FILE} (共 {len(series)} 天) ===")


# ---------------------------------------------------------------------------
# 3) 打印一张干净的表格
# ---------------------------------------------------------------------------
print()
print("=" * 100)
print(f"{'日期':<12}{'涨停':>6}{'跌停':>6}{'连板':>6}{'晋级率':>10}{'断板':>6}{'炸板率':>10}{'情绪':>8}")
print("-" * 100)
for r in series:
    pr = f"{r['promotionRate']*100:.1f}%" if r["promotionRate"] is not None else "—"
    br = f"{r['breakRate']*100:.1f}%" if r["breakRate"] is not None else "—"
    print(
        f"{r['tradeDate']:<12}"
        f"{r['limitUp']:>6}"
        f"{r['limitDown']:>6}"
        f"{str(r['maxHeight']):>6}"
        f"{pr:>10}"
        f"{r['brokenCount']:>6}"
        f"{br:>10}"
        f"{r['sentimentLevel']:>8}"
    )
print("=" * 100)


# ---------------------------------------------------------------------------
# 4) 连板梯队明细 (每天)
# ---------------------------------------------------------------------------
print()
print("=" * 100)
print("连板梯队 明细 (每天每板 stock 列表)")
print("=" * 100)
for r in series:
    print()
    print(f"--- {r['tradeDate']}  最高 {r['maxHeight']} 板  |  涨停 {r['limitUp']} | 情绪 {r['sentimentLevel']} ---")
    dist = r.get("distribution") or []
    if not dist:
        print("  (无梯队数据)")
        continue
    for tier in dist:
        streak = tier.get("streak")
        count = tier.get("count")
        stocks = tier.get("stocks") or []
        if len(stocks) <= 8:
            stock_str = "  ".join(
                f"{s.get('code','')[:6]}/{s.get('name') or '?'}" for s in stocks
            )
        else:
            head = "  ".join(
                f"{s.get('code','')[:6]}/{s.get('name') or '?'}" for s in stocks[:6]
            )
            stock_str = f"{head}  ... (+{len(stocks) - 6})"
        print(f"  {streak}板 ×{count:>3}  |  {stock_str}")


# ---------------------------------------------------------------------------
# 5) 最新一天 (2026-06-12) 完整 5 大块
# ---------------------------------------------------------------------------
latest = series[-1] if series else None
if latest:
    print()
    print("=" * 100)
    print(f"最新一天 ({latest['tradeDate']}) 完整 5 大块")
    print("=" * 100)
    print()
    print(f"【1 涨停】共 {latest['limitUp']} 只")
    print(f"【2 跌停】共 {latest['limitDown']} 只")
    print()
    print(f"【3 连板梯队】最高 {latest['maxHeight']} 板")
    for tier in (latest.get("distribution") or []):
        s = tier.get("streak")
        c = tier.get("count")
        names = ", ".join(
            (st.get("name") or st.get("code") or "?") for st in (tier.get("stocks") or [])
        )
        print(f"   {s}板 ×{c}: {names}")
    print()
    print(f"【4 炸板率】 {latest.get('touched')} 触 / {latest.get('broken')} 炸 / 率 {(latest.get('breakRate') or 0)*100:.1f}%")
    print()
    print(f"【5 情绪】 {latest['sentimentLevel']}")
