"""volatility_sentiment 端到端 smoke test.

用法:
    python scripts/smoke_test_volatility_sentiment.py

跑通条件:
  1. calc_volatility_sentiment(最近交易日) 返回 dict (不返 None)
  2. sentiment_score 在 [0, 100] 范围内
  3. percentile_1y 在 [0, 1] 范围内
  4. 落库后再查表能查到 (cache-aside 验证)
  5. history 查近 30 天能返回 ≥ 0 条
"""
from __future__ import annotations

import io
import json
import sys
from datetime import date, timedelta
from pathlib import Path

# 修 Windows gbk 编码: 把 stdout/stderr 强制 utf-8 (含 ✓ 中文)
if sys.platform == "win32":
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
    # 老 python 没 reconfigure, 用 io.TextIOWrapper 兜底
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.adapters.market.duckdb_store import conn, get_conn
from backend.repositories.market.volatility_sentiment_repo import (
    calc_volatility_sentiment,
    calc_volatility_sentiment_cached,
    coverage,
    get_volatility_sentiment,
    get_volatility_sentiment_history,
    save_volatility_sentiment,
)


def _ensure_schema() -> None:
    from backend.adapters.market.duckdb_store import init_schema
    init_schema()


OK = "[OK]"
FAIL = "[FAIL]"
WARN = "[WARN]"


def main() -> int:
    _ensure_schema()
    print("=== 1. coverage (运行前) ===")
    print(json.dumps(coverage(), indent=2, ensure_ascii=False))

    con = get_conn()
    r = con.execute(
        "SELECT MAX(trade_date) FROM index_daily_raw WHERE code = 'sh000300'"
    ).fetchone()
    if not r or not r[0]:
        print(f"{FAIL}: index_daily_raw 没有任何 sh000300 数据, 请先跑 fetch_index_history.py --days=300")
        return 1
    target = r[0]
    if isinstance(target, str):
        target = date.fromisoformat(target)
    print(f"\n=== 2. calc_volatility_sentiment({target.isoformat()}) ===")

    payload = calc_volatility_sentiment(target)
    if payload is None:
        print(f"{FAIL}: 算不出来, 可能是历史不足 (< 22 天), 请跑 fetch_index_history.py --days=300")
        return 1
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    score = payload["sentimentScore"]
    pct = payload["percentile1y"]
    vol = payload["realizedVol20d"]
    sample = payload.get("sampleCount", 0)
    if not (0 <= score <= 100):
        print(f"{FAIL}: sentimentScore {score} 超出 [0, 100]")
        return 1
    if not (0 <= pct <= 1):
        print(f"{FAIL}: percentile1y {pct} 超出 [0, 1]")
        return 1
    if vol < 0 or vol > 200:
        print(f"{WARN}: realizedVol20d {vol}% 不在常规区间 [0, 200]")
    if sample < 100:
        print(f"{WARN}: sampleCount={sample} (< 100), 分位不稳健, 建议先跑 fetch_index_history.py --days=300")
    else:
        print(f"{OK} 范围检查通过 (sample={sample})")

    # 3. 落盘
    print(f"\n=== 3. save + get (cache-aside) ===")
    with conn() as c:
        c.execute("DELETE FROM volatility_sentiment_daily WHERE trade_date = ?", [target])
    save_volatility_sentiment(payload)
    fetched = get_volatility_sentiment(target)
    if fetched is None:
        print(f"{FAIL}: 落盘后查不到")
        return 1
    if abs(fetched["sentimentScore"] - payload["sentimentScore"]) > 0.01:
        print(f"{FAIL}: 落盘前后 sentimentScore 不一致: {payload['sentimentScore']} vs {fetched['sentimentScore']}")
        return 1
    print(f"{OK} 落盘 + 读 OK (fromCache={fetched.get('fromCache')}, score={fetched['sentimentScore']})")

    # 4. cached 版
    print(f"\n=== 4. calc_volatility_sentiment_cached({target.isoformat()}, force=True) ===")
    cached_payload = calc_volatility_sentiment_cached(target, force=True)
    if cached_payload is None:
        print(f"{FAIL}: cached 返 None")
        return 1
    print(f"  score={cached_payload['sentimentScore']} vol={cached_payload['realizedVol20d']}")
    print(f"{OK} cached 入口正常")

    # 5. history
    print(f"\n=== 5. history (近 30 天) ===")
    end_d = target
    start_d = end_d - timedelta(days=30)
    hist = get_volatility_sentiment_history(start_d, end_d)
    print(f"  区间 {start_d} ~ {end_d}, 命中 {len(hist)} 条")
    if hist:
        print(f"  最早: {hist[0]['tradeDate']} score={hist[0]['sentimentScore']}")
        print(f"  最晚: {hist[-1]['tradeDate']} score={hist[-1]['sentimentScore']}")
    print(f"{OK} history 正常")

    # 6. coverage
    print(f"\n=== 6. coverage (运行后) ===")
    print(json.dumps(coverage(), indent=2, ensure_ascii=False))

    print(f"\n{OK} smoke test 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
