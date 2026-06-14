"""模拟"上一个交易日" 跑一遍 limitEmotion.

今天 2026-06-14 是周日, 非交易日. 走真实 API 永远拿到 ``dataStatus=empty`` (因为
``reference/market-limit/daily/`` 空). 这里把 ``is_trading_day`` / ``_beijing_now``
打补丁, 假装今天是上一个交易日 2026-06-12 (周五), 然后走"交易日 realtime"路径:

  1) 拉沪深 A 股全量实时 (eltdx list_by_category)
  2) 跑 filter / 涨跌停 / 连板聚合
  3) 落盘 ``reference/market-limit/daily/2026-06-12.json`` (等价于盘后 15:30 落盘)
  4) 调 ``build_limit_emotion()`` (非交易日分支, 读 daily 聚合) 模拟前端轮询
  5) 输出面板需要的 4 大块: 涨停 / 跌停 / 连板高度 / 炸板率 + 情绪文案

注意: 这是"逻辑测试", 实时拉到的不是真正的周五收盘 (周日 eltdx 也只是
返回最后一笔报价), 只能验证 ``daily<->latest`` 双向 pipeline 是否通.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# 仓库根目录
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 假装"今天" = 2026-06-12 (周五) — 模拟上一个交易日
PREV_TD = date(2026, 6, 12)
FAKE_NOW = datetime(2026, 6, 12, 15, 30, 0)  # 盘后 15:30 落盘时刻


# ---------------------------------------------------------------------------
# 在 import 之前先打补丁, 让 trading_calendar / 服务模块拿到假日期
# ---------------------------------------------------------------------------
import backend.services.stock.trading_calendar as tc  # noqa: E402
import backend.services.stock.limit_emotion_service as svc  # noqa: E402


# 1) 交易日历: 2026-06-12 是周五, 视为交易日
_original_today = tc._today
def _patched_today() -> date:
    return PREV_TD
tc._today = _patched_today  # type: ignore[assignment]
tc._today_dt = lambda: FAKE_NOW  # type: ignore[assignment]

# 2) 服务模块的 _beijing_now / _detect_market_status 走自己的 helper, 单独打
_original_beijing_now = svc._beijing_now
svc._beijing_now = lambda: FAKE_NOW  # type: ignore[assignment]

# 3) universe cache 强制重算
svc._universe_cache = None
svc._universe_loaded_at = 0.0

print(f"=== 模拟上一个交易日  PREV_TD={PREV_TD.isoformat()}  (周日 {date(2026,6,14).isoformat()}) ===")
print(f"is_trading_day({PREV_TD.isoformat()}) = {tc.is_trading_day(PREV_TD)}")
print(f"previous_trading_day({PREV_TD.isoformat()}) = {tc.previous_trading_day(PREV_TD).isoformat()}")
print()

# ---------------------------------------------------------------------------
# 1. 拉实时 (走 eltdx.list_by_category) — 注意: 周日 eltdx 也只是返回最后报价
# ---------------------------------------------------------------------------
print("=== 1) 拉沪深 A 股实时行情 ===")
quotes, source, err = svc._fetch_realtime_quotes()
print(f"  quotes: {len(quotes)}  source: {source}  err: {err}")
if not quotes:
    print("  !! 实时拉取为空, 退出 (eltdx 不可用)")
    sys.exit(1)

names_filled = sum(1 for q in quotes if q.get("name") and not str(q.get("name")).isdigit())
print(f"  name 填充率: {names_filled} / {len(quotes)}")

# ---------------------------------------------------------------------------
# 2. 落盘 daily/<2026-06-12>.json (等价于 scheduler 15:30 收盘落盘)
# ---------------------------------------------------------------------------
print()
print("=== 2) 落盘 daily snapshot ===")
out = svc.snapshot_today_daily(force=True)
if not out:
    print("  !! snapshot_today_daily 返回 None, 落盘失败")
    sys.exit(1)
print(f"  tradeDate: {out.get('tradeDate')}")
print(f"  marketStatus: {out.get('marketStatus')}")
print(f"  stockCount: {out.get('stockCount')}")
print(f"  source: {out.get('source')}")
daily_path = Path("reference/market-limit/daily") / f"{PREV_TD.isoformat()}.json"
print(f"  written to: {daily_path}  (size={daily_path.stat().st_size if daily_path.exists() else 0} bytes)")

# ---------------------------------------------------------------------------
# 3. 模拟"周日"再调 build_limit_emotion (非交易日 → 走 daily 聚合分支)
# ---------------------------------------------------------------------------
print()
print("=== 3) 模拟周日 (今天) 调 build_limit_emotion, 期望走 daily 聚合 ===")

# 切回"今天是周日", 触发非交易日分支
_today_real = date(2026, 6, 14)
tc._today = lambda: _today_real  # type: ignore[assignment]
tc._today_dt = lambda: datetime(2026, 6, 14, 17, 30, 0)  # type: ignore[assignment]
svc._beijing_now = lambda: datetime(2026, 6, 14, 17, 30, 0)  # type: ignore[assignment]

payload = svc.build_limit_emotion(force=True)

print()
print("=== 4) 面板展示用数据 ===")
print(f"  tradeDate:    {payload.get('tradeDate')}")
print(f"  marketStatus: {payload.get('marketStatus')}")
print(f"  dataStatus:   {payload.get('dataStatus')}")
print(f"  updateTime:   {payload.get('updateTime')}")
print()
print(f"  涨停: {payload['limitUp']['count']}")
print(f"  跌停: {payload['limitDown']['count']}")
print(f"  连板高度: {payload['streak']['maxHeight']}")
print(f"  连板梯队: {[(r['streak'], r['count']) for r in payload['streak']['distribution'][:6]]}")
print(f"  连板情绪: {payload['streak']['sentiment']['level']}  /  {payload['streak']['sentiment']['text']}")
print(f"  触板: {payload['breakBoard']['touchedCount']}  /  炸板: {payload['breakBoard']['brokenCount']}  /  炸板率: {payload['breakBoard']['rate']}")
print(f"  晋级率: {payload['streak']['promotion']['overallRate']}")
print(f"  断板: {payload['streak']['broken']['count']}  /  高位断板: {payload['streak']['broken']['highStreakBrokenCount']}")
print(f"  领头: {payload['streak']['leaders'][:5]}")
print()
print("  _meta:")
for k, v in (payload.get("_meta") or {}).items():
    print(f"    {k}: {v}")

# 顺便写出 5 只涨停 + 5 只跌停, 验证 is_st / is_new 过滤
print()
print("=== 5) 样例明细 (前 5 涨停) ===")
for s in (payload['limitUp']['stocks'] or [])[:5]:
    code = s.get('code', '')
    name = (s.get('name') or '')[:18]
    chg = s.get('changePct')
    up = s.get('limitUpPrice')
    print(f"   {code.ljust(10)} name={name.ljust(18)} chg={chg}  limitUpPrice={up}")
print()
print("=== 6) 样例明细 (前 5 跌停) ===")
for s in (payload['limitDown']['stocks'] or [])[:5]:
    code = s.get('code', '')
    name = (s.get('name') or '')[:18]
    chg = s.get('changePct')
    down = s.get('limitDownPrice')
    print(f"   {code.ljust(10)} name={name.ljust(18)} chg={chg}  limitDownPrice={down}")
print()
print("=== 7) 阈值分布 (验证板块判定) ===")
buckets = {'10%': 0, '20%': 0, '30%': 0, '5%ST': 0, 'other': 0}
for s in payload['limitUp']['stocks'] or []:
    cp = s.get('changePct')
    if cp is None:
        continue
    a = abs(cp)
    if a >= 29:
        buckets['30%'] += 1
    elif a >= 19:
        buckets['20%'] += 1
    elif 4.5 <= a < 5.5:
        buckets['5%ST'] += 1
    elif a >= 9.5:
        buckets['10%'] += 1
    else:
        buckets['other'] += 1
print(f"  {buckets}")

# 还原
tc._today = _original_today
