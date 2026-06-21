"""时间工具: CST 格式时间字符串."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

_CST = timezone(timedelta(hours=8))


def cst_now_str() -> str:
    """返当前北京时间字符串 (UTC+8), 例如 '2026-06-21 22:39:54 CST'."""
    utc_now = datetime.now(timezone.utc)
    cst = utc_now.astimezone(_CST)
    return cst.strftime("%Y-%m-%d %H:%M:%S") + " CST"
