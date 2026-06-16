"""
回填历史涨跌停数据（腾讯版）：60 个交易日。

使用腾讯日线接口 (fetch_stock_klines_from_tencent)，每只股票 500 条日线，
按 trade_date 聚合到 reference/market-limit/daily/<date>.json。

eltdx 限流严重，改为腾讯源 + 单线程 + 间歇策略。
每只股票之间 sleep 1 秒，5530 只约 1.5 小时。

用法:
  python scripts/backfill_limit_history.py [--days 60] [--sleep 1]
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import date, datetime
from pathlib import Path

# ---------------------------------------------------------------
# 路径设置
# ---------------------------------------------------------------
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from backend.config.settings import MARKET_LIMIT_DAILY_DIR
from backend.services.stock.limit_emotion_service import (
    _threshold_for,
    _write_json_atomic,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill")


# ---------------------------------------------------------------
# 涨跌停计算（从腾讯日线 bar 推导）
# ---------------------------------------------------------------
def _is_st_by_name(name: str) -> bool:
    if not name:
        return False
    upper = name.upper()
    return upper.startswith("ST") or upper.startswith("*ST") or "退" in name


def _calc_limit_from_tencent_bar(
    close: float,
    high: float,
    pre_close: float,
    is_st: bool,
    code: str,
    tolerance: float = 0.0001,
) -> tuple[bool, bool, float | None, float | None, bool, bool]:
    if pre_close is None or pre_close <= 0:
        return False, False, None, None, False, False
    base = 4.95 if is_st else _threshold_for(code)
    limit_up = round(pre_close * (1 + base / 100.0), 4)
    limit_down = round(pre_close * (1 - base / 100.0), 4)
    is_up = close >= limit_up * (1 - tolerance)
    is_down = close <= limit_down * (1 + tolerance)
    is_touched = high >= limit_up * (1 - tolerance)
    is_broken = is_touched and not is_up
    return is_up, is_down, limit_up, limit_down, is_touched, is_broken


# ---------------------------------------------------------------
# 拉单只股票的日线（腾讯接口）
# ---------------------------------------------------------------
def _fetch_stock_bars(code: str) -> tuple[str, str, list[dict]] | None:
    """
    返回 (code, name, bars) 或 None。
    bars 里每项含 trade_date / open / close / high / low / volume。
    """
    try:
        from backend.adapters.market.tencent import fetch_stock_klines_from_tencent
        bars = fetch_stock_klines_from_tencent("stock", code, "1d", "none")
        if not bars:
            return None
        return code, code, bars
    except Exception as exc:
        logger.debug("fetch %s failed: %s", code, exc)
        return None


# ---------------------------------------------------------------
# 从 bars 解析每日涨跌停记录（用 trade_date 做日期键）
# ---------------------------------------------------------------
def _parse_bars_to_rows(
    code: str,
    bars: list[dict],
    is_st: bool,
) -> list[dict]:
    """
    按 trade_date 排序的 bars，计算每根 bar 的涨跌停状态。
    注意：bars 已经是按时间升序的（ oldest -> newest）。
    """
    rows = []
    for i, bar in enumerate(bars):
        trade_date_str = bar.get("trade_date")
        if not trade_date_str:
            continue
        try:
            trade_date = date.fromisoformat(str(trade_date_str)[:10])
        except Exception:
            continue

        close = float(bar.get("close") or 0)
        high = float(bar.get("high") or 0)
        low = float(bar.get("low") or 0)

        # 前收 = 前一根 bar 的 close
        pre_close = None
        if i > 0:
            pre_close = float(bars[i - 1].get("close") or 0)

        is_up, is_down, up_price, dn_price, is_touched, is_broken = _calc_limit_from_tencent_bar(
            close, high, pre_close, is_st, code
        )

        change_pct = None
        if pre_close and pre_close > 0:
            change_pct = round((close - pre_close) / pre_close * 100, 4)

        rows.append({
            "code": code,
            "name": code,
            "latestPrice": close,
            "highPrice": high,
            "lowPrice": low,
            "preClosePrice": pre_close,
            "limitUpPrice": up_price,
            "limitDownPrice": dn_price,
            "changePct": change_pct,
            "isLimitUp": is_up,
            "isLimitDown": is_down,
            "isTouchedLimitUp": is_touched,
            "isBrokenLimitUp": is_broken,
            "_tradeDate": trade_date,  # 用于按日期聚合
            # 连板相关（后续填充）
            "limitUpStreak": 0,
            "previousLimitUpStreak": 0,
            "isPromoted": False,
            "isBrokenStreak": False,
        })
    return rows


# ---------------------------------------------------------------
# 获取全量股票列表
# ---------------------------------------------------------------
def _list_all_codes() -> list[tuple[str, str]]:
    try:
        from backend.services.stock.stock_universe_service import load_latest
        blob = load_latest() or {}
    except Exception as exc:
        logger.warning("load_latest failed: %s", exc)
        blob = {}

    out = []
    seen = set()
    for s in (blob.get("stocks") or []):
        code = str(s.get("code") or "").strip()
        name = (s.get("name") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        bare = code[-6:] if len(code) >= 6 else code
        out.append((bare, name))
    return out


# ---------------------------------------------------------------
# 主逻辑
# ---------------------------------------------------------------
def run(days: int = 60, sleep_per_stock: float = 1.0, force: bool = False):
    today = date.today()

    # 计算目标日期范围
    from backend.services.stock.trading_calendar import previous_trading_day
    target_dates: list[date] = []
    p = today
    for _ in range(days):
        p = previous_trading_day(p)
        target_dates.append(p)
    target_dates.sort()
    logger.info(
        "Target dates: %s .. %s (%d trading days)",
        target_dates[0], target_dates[-1], len(target_dates),
    )

    # 加载全量股票
    codes = _list_all_codes()
    logger.info("Total stocks: %d", len(codes))

    # 按日期聚合
    date_rows: dict[date, list[dict]] = {d: [] for d in target_dates}
    date_stocks: dict[date, set[str]] = {d: set() for d in target_dates}  # 防重

    t0 = time.time()
    fetched = 0
    failed = 0

    for i, (code, name) in enumerate(codes):
        if (i + 1) % 100 == 0:
            logger.info("Progress: %d / %d stocks ...", i + 1, len(codes))

        result = _fetch_stock_bars(code)
        time.sleep(sleep_per_stock)

        if not result:
            failed += 1
            continue

        _, _, bars = result
        is_st = _is_st_by_name(name)
        rows = _parse_bars_to_rows(code, bars, is_st)

        for row in rows:
            d = row.get("_tradeDate")
            if d is None:
                continue
            if d in date_rows and code not in date_stocks[d]:
                date_rows[d].append(row)
                date_stocks[d].add(code)

        fetched += 1

    elapsed = time.time() - t0
    logger.info(
        "Fetched %d / %d stocks in %.1fs (failed: %d, elapsed: %.1fs)",
        fetched, len(codes), elapsed, failed, elapsed,
    )

    # -----------------------------------------------------------
    # 填充连板 streak（需要前一天的结果）
    # -----------------------------------------------------------
    for idx, d in enumerate(sorted(target_dates)):
        rows = date_rows[d]
        if idx == 0:
            for r in rows:
                if r["isLimitUp"]:
                    r["limitUpStreak"] = 1
        else:
            prev_date = sorted(target_dates)[idx - 1]
            prev_map = {r["code"]: r for r in date_rows[prev_date]}
            for r in rows:
                prev = prev_map.get(r["code"])
                prev_streak = prev["limitUpStreak"] if prev else 0
                r["previousLimitUpStreak"] = prev_streak
                if r["isLimitUp"]:
                    r["limitUpStreak"] = prev_streak + 1
                    r["isPromoted"] = (prev_streak > 0)
                else:
                    r["limitUpStreak"] = 0
                    r["isBrokenStreak"] = (prev_streak > 0)

    # -----------------------------------------------------------
    # 落盘
    # -----------------------------------------------------------
    MARKET_LIMIT_DAILY_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat(timespec="seconds")
    total_written = 0

    for d in sorted(target_dates):
        target = MARKET_LIMIT_DAILY_DIR / f"{d.isoformat()}.json"
        if not force and target.exists():
            existing = json.loads(target.read_text(encoding="utf-8"))
            if existing.get("stocks") and len(existing["stocks"]) > 1000:
                logger.info("Skip %s (exists, %d stocks)", d, len(existing["stocks"]))
                continue

        rows = date_rows[d]
        # 清理 _tradeDate / _barTime 等临时字段
        for r in rows:
            r.pop("_tradeDate", None)
            r.pop("_barTime", None)

        payload = {
            "tradeDate": d.isoformat(),
            "updateTime": now,
            "marketStatus": "closed",
            "stockCount": len(rows),
            "source": f"tencent.daily_kline_backfill({fetched} stocks fetched)",
            "stocks": rows,
        }
        _write_json_atomic(target, payload)

        lu = sum(1 for r in rows if r["isLimitUp"])
        ld = sum(1 for r in rows if r["isLimitDown"])
        logger.info("Wrote %s: %d stocks, limitUp=%d, limitDown=%d", d, len(rows), lu, ld)
        total_written += 1

    logger.info("Done! Wrote %d daily files.", total_written)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="回填历史涨跌停数据（腾讯版）")
    parser.add_argument("--days", type=int, default=60, help="回填多少个交易日（默认 60）")
    parser.add_argument(
        "--sleep", type=float, default=1.0, help="每只股票之间休息秒数（默认 1.0）"
    )
    parser.add_argument("--force", action="store_true", help="强制覆盖已有文件")
    args = parser.parse_args()
    run(days=args.days, sleep_per_stock=args.sleep, force=args.force)
