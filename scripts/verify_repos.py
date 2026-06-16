"""Smoke test all 4 repos: kline / indicator / limit / stock_meta.

Run: python -m scripts.verify_repos
"""
import time
from datetime import date

from backend.repositories.market.kline_repo import (
    get_daily_kline, get_latest_trade_date, has_qfq,
    list_codes_with_qfq, coverage_gap,
)
from backend.repositories.market.indicator_repo import (
    calc_ma, calc_macd, calc_kdj, calc_boll, calc_ma_codes,
)
from backend.repositories.market.limit_repo import (
    get_limit_streak_history, get_today_limit_snapshot,
    get_limit_streak_distribution,
)
from backend.repositories.market.stock_meta_repo import (
    get_stock_meta, list_universe, get_board_type, get_threshold,
    coverage_summary,
)


def section(title: str):
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def main():
    section("1. kline_repo")
    bars = get_daily_kline("000001", adjust="qfq", limit=5)
    print(f"  000001 last 5 bars: {len(bars)} returned")
    print(f"  first bar keys: {list(bars[0].keys())}")
    print(f"  sample: trade_date={bars[0]['trade_date']}, close={bars[0]['close']}, ts={bars[0]['timestamp']}")
    assert "timestamp" in bars[0] and "trade_date" in bars[0] and bars[0]["close"] > 0
    print(f"  has_qfq('000001') = {has_qfq('000001')}")
    print(f"  has_qfq('999999') = {has_qfq('999999')}")
    print(f"  latest_trade_date('000001') = {get_latest_trade_date('000001')}")
    print(f"  codes with qfq: {len(list_codes_with_qfq())}")

    section("2. indicator_repo")
    t0 = time.time()
    ma = calc_ma("000001", windows=[5, 10, 20], limit=5)
    print(f"  MA5/10/20 last 5 ({time.time()-t0:.2f}s):")
    for row in ma:
        print(f"    {row['trade_date']}: close={row['close']:.2f}  "
              f"ma5={row['ma5']:.2f}  ma10={row['ma10']:.2f}  ma20={row['ma20']:.2f}")
    assert ma[-1]["ma5"] is not None and ma[-1]["ma10"] is not None

    t0 = time.time()
    macd = calc_macd("000001", limit=3)
    print(f"  MACD last 3 ({time.time()-t0:.2f}s):")
    for row in macd:
        print(f"    {row['trade_date']}: macd={row['macd']:.4f}  signal={row['signal']:.4f}  hist={row['hist']:.4f}")

    t0 = time.time()
    kdj = calc_kdj("000001", limit=3)
    print(f"  KDJ last 3 ({time.time()-t0:.2f}s):")
    for row in kdj:
        print(f"    {row['trade_date']}: k={row['k']:.2f}  d={row['d']:.2f}  j={row['j']:.2f}")

    t0 = time.time()
    boll = calc_boll("000001", limit=3)
    print(f"  BOLL last 3 ({time.time()-t0:.2f}s):")
    for row in boll:
        print(f"    {row['trade_date']}: mid={row['mid']:.2f}  upper={row['upper']:.2f}  lower={row['lower']:.2f}")

    code = calc_ma_codes("000001", "2026-06-15")
    print(f"  ma_codes for 000001 on 2026-06-15: {code['ma_codes']}  "
          f"close={code['close']:.2f}  ma10={code['ma10']:.2f}")

    section("3. limit_repo")
    t0 = time.time()
    hist = get_limit_streak_history("000001", end="2026-06-15")
    print(f"  000001 streak history: {len(hist)} days in {time.time()-t0:.2f}s")
    print(f"  last 3:")
    for row in hist[-3:]:
        print(f"    {row['trade_date']}: close={row['close']:.2f}  "
              f"is_limit_up={row['is_limit_up']}  streak={row['streak']}")

    t0 = time.time()
    snap = get_today_limit_snapshot("2026-06-15")
    print(f"  2026-06-15 snapshot: {len(snap)} stocks in {time.time()-t0:.2f}s")
    if snap:
        print(f"  top 3 by streak:")
        for row in snap[:3]:
            print(f"    {row['code']} {row['name']}: streak={row['limitUpStreak']}  "
                  f"change={row['changePct']}%  isLimitUp={row['isLimitUp']}")

    dist = get_limit_streak_distribution("2026-06-15")
    print(f"  distribution: maxHeight={dist['maxHeight']}  "
          f"promoted_rate={dist['promoted']['overallRate']}  "
          f"broken_count={dist['broken']['count']}")

    section("4. stock_meta_repo")
    for code in ("000001", "600519", "300750", "688981", "920000"):
        m = get_stock_meta(code)
        if m:
            print(f"  {code}: name={m['name']}  board={m['board']}  threshold={m['threshold']}  is_st={m['is_st']}")

    print(f"  get_board_type('600519') = {get_board_type('600519')}")
    print(f"  get_threshold('300750', is_st=False) = {get_threshold('300750', False)}")
    print(f"  get_threshold('300750', is_st=True) = {get_threshold('300750', True)}")
    print(f"  coverage: {coverage_summary()}")

    section("5. Perf smoke")
    for code, start in [("600519", "2020-01-01"), ("000001", "1990-01-01"), ("920000", "2020-01-01")]:
        t0 = time.time()
        bars = get_daily_kline(code, "qfq", start, "2026-06-15")
        elapsed = time.time() - t0
        print(f"  {code} qfq {start}..2026-06-15: {len(bars):>5} bars in {elapsed:.3f}s")

    print()
    print("All checks passed.")


if __name__ == "__main__":
    main()
