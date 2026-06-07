"""
A 股交易日历工具.

eltdx 库本身没有交易日历接口, 这里用「周末 + 内置节假日集合」的本地方案,
每年初按国务院办公厅发布的放假通知维护一次 ``HOLIDAYS`` 即可.

用法::

    from backend.services.stock.trading_calendar import (
        is_trading_day, previous_trading_day, next_trading_day,
    )

    is_trading_day()                # True / False (默认查今天)
    is_trading_day(date(2025, 10, 1))  # False (国庆)
    previous_trading_day()          # 上一交易日 date
    next_trading_day()              # 下一交易日 date
"""
from __future__ import annotations

import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# 节假日集合 (date -> name). 周末不需要列, 函数里直接 weekday() 判定.
# 维护: 每年初按国务院办公厅放假通知更新一次.
# ---------------------------------------------------------------------------
# A 股调休日 (周末补班) 单独放 ``WORKDAYS_OVERTIME`` —— 这些周六/周日是交易日.
# 不补班的周末 -> 非交易日.
HOLIDAYS: dict[date, str] = {
    # ---- 2025 ----
    date(2025, 1, 1): "元旦",
    date(2025, 1, 28): "春节",
    date(2025, 1, 29): "春节",
    date(2025, 1, 30): "春节",
    date(2025, 1, 31): "春节",
    date(2025, 2, 3): "春节",
    date(2025, 2, 4): "春节",
    date(2025, 4, 4): "清明",
    date(2025, 4, 5): "清明",
    date(2025, 4, 6): "清明",
    date(2025, 5, 1): "劳动节",
    date(2025, 5, 2): "劳动节",
    date(2025, 5, 5): "劳动节",
    date(2025, 5, 31): "端午",
    date(2025, 6, 2): "端午",
    date(2025, 10, 1): "国庆",
    date(2025, 10, 2): "国庆",
    date(2025, 10, 3): "国庆",
    date(2025, 10, 6): "国庆",
    date(2025, 10, 7): "国庆",
    date(2025, 10, 8): "国庆",
    # ---- 2026 ----
    date(2026, 1, 1): "元旦",
    date(2026, 1, 2): "元旦",
    date(2026, 2, 17): "春节",
    date(2026, 2, 18): "春节",
    date(2026, 2, 19): "春节",
    date(2026, 2, 20): "春节",
    date(2026, 2, 23): "春节",
    date(2026, 2, 24): "春节",
    date(2026, 4, 6): "清明",
    date(2026, 5, 1): "劳动节",
    date(2026, 5, 4): "劳动节",
    date(2026, 5, 5): "劳动节",
    date(2026, 6, 19): "端午",
    date(2026, 9, 25): "中秋",
    date(2026, 10, 1): "国庆",
    date(2026, 10, 2): "国庆",
    date(2026, 10, 5): "国庆",
    date(2026, 10, 6): "国庆",
    date(2026, 10, 7): "国庆",
    # ---- 2027 (预估, 国务院未发时按规则推断) ----
    date(2027, 1, 1): "元旦",
}

# 周末调休补班日 (周末但实际是交易日).
# 不放这里的话, 这些周末会被 weekday() 判成非交易日.
WORKDAYS_OVERTIME: set[date] = {
    # 2025
    date(2025, 1, 26),  # 周日补班
    date(2025, 2, 8),   # 周六补班
    date(2025, 4, 27),  # 周日补班
    date(2025, 9, 28),  # 周日补班
    date(2025, 10, 11), # 周六补班
    # 2026
    date(2026, 1, 4),   # 周日补班
    date(2026, 2, 14),  # 周六补班
    date(2026, 2, 28),  # 周日补班
    date(2026, 5, 9),   # 周六补班
    date(2026, 9, 27),  # 周日补班
    date(2026, 10, 10), # 周六补班
}

# 节假日文件路径 (允许运维手动加临时休市, 比如临时停市).
_OVERRIDE_PATH: Path | None = None
_override_lock = threading.Lock()
_override_cache: set[date] | None = None
_override_workday_cache: set[date] | None = None


def _extra_holidays_path() -> Path | None:
    """运行时可手动维护的临时休市 JSON, 一行一个 ``YYYY-MM-DD`` (或带 name 注释)."""
    global _OVERRIDE_PATH
    if _OVERRIDE_PATH is not None:
        return _OVERRIDE_PATH
    try:
        from backend.config.settings import STOCK_UNIVERSE_DIR
        p = STOCK_UNIVERSE_DIR / "trading_calendar_overrides.txt"
    except Exception:
        return None
    _OVERRIDE_PATH = p
    return p


def _load_overrides() -> tuple[set[date], set[date]]:
    """读 override 文件. 返回 (extra_holidays, extra_workdays)."""
    p = _extra_holidays_path()
    if not p or not p.exists():
        return set(), set()
    hols: set[date] = set()
    works: set[date] = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        # 形如 "2025-12-31 # 临时停市" 或 "2025-09-28 +work"
        try:
            d = datetime.strptime(s.split()[0], "%Y-%m-%d").date()
        except ValueError:
            continue
        if "+work" in s or "+workday" in s:
            works.add(d)
        else:
            hols.add(d)
    return hols, works


def _today() -> date:
    return datetime.now().date()


def is_trading_day(d: date | None = None) -> bool:
    """``d`` (默认今天) 是 A 股交易日."""
    if d is None:
        d = _today()
    if d in WORKDAYS_OVERTIME:
        return True
    extra_hols, extra_works = _load_overrides()
    if d in extra_works:
        return True
    if d in extra_hols:
        return False
    if d in HOLIDAYS:
        return False
    # 周末 -> 非交易日
    if d.weekday() >= 5:
        return False
    return True


def _walk(d: date, step: int) -> date:
    """从 ``d`` 出发, 沿 ``step`` 方向 (-1=上, +1=下) 走, 跳过非交易日."""
    cur = d
    while True:
        cur = cur + timedelta(days=step)
        if is_trading_day(cur):
            return cur


def previous_trading_day(d: date | None = None) -> date:
    """返回 ``d`` (含) 之前的最近一个交易日."""
    if d is None:
        d = _today()
    if is_trading_day(d):
        # ``d`` 本身是交易日 -> 跳过它
        return _walk(d, -1)
    return _walk(d, -1)


def next_trading_day(d: date | None = None) -> date:
    if d is None:
        d = _today()
    return _walk(d, 1)


def is_weekend(d: date) -> bool:
    return d.weekday() >= 5


__all__ = [
    "is_trading_day",
    "previous_trading_day",
    "next_trading_day",
    "is_weekend",
    "is_trade_time",
    "HOLIDAYS",
    "WORKDAYS_OVERTIME",
]


# ---------------------------------------------------------------------------
# 交易时间窗: 9:30-11:30 / 13:00-15:00
# ---------------------------------------------------------------------------
def is_trade_time(t: datetime | None = None) -> bool:
    """``t`` (默认当前北京时间) 是否处于 A 股交易时段.

    A 股:
      - 上午 09:30:00 - 11:30:00
      - 下午 13:00:00 - 15:00:00
    """
    if t is None:
        t = _today_dt()
    if t.weekday() >= 5:
        return False
    if not is_trading_day(t.date()):
        return False
    hm = t.hour * 60 + t.minute
    morning = 9 * 60 + 30 <= hm <= 11 * 60 + 30
    afternoon = 13 * 60 <= hm <= 15 * 60
    return morning or afternoon


def _today_dt() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)
