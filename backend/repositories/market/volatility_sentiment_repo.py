"""波动率情绪 (Volatility Sentiment) 仓储.

公式 (v1.0):
  1. 标的: 沪深300 (sh000300), 走 duckdb.index_daily_raw
  2. 日收益率: r_t = (close_t - close_{t-1}) / close_{t-1}
  3. 20 日年化波动率:
       realized_vol_20d = std(r_{t-19} .. r_t) × √252 × 100
     单位 %, 类同 AKShare / Wind 报法
  4. 历史分位数 (近 1 年, 默认 252 个交易日滚动):
     sample = 过去 252 天的 vol 值 (不含今天)
     percentile_1y = count(sample <= 当前 vol) / len(sample)  ∈ [0, 1]
  5. 情绪得分 (反向):
     sentiment_score = round((1 - percentile_1y) × 100, 2)  ∈ [0, 100]
     波动率越低 → percentile 越低 → 1-percentile 越高 → 得分越高
     波动率越高 → percentile 越高 → 1-percentile 越低 → 得分越低

颜色逻辑 (跟限仓情绪综合分 / 风险偏好同空间):
  - score >= 70  平静  (绿, 情绪好, "安全" 心态)
  - score >= 40  正常  (slate)
  - score < 40   波动  (红, 情绪差, 分歧大 / 恐慌)

数据源: duckdb.index_daily_raw (沪深300 = sh000300)
  - 跟 risk_appetite_daily / ma_count_daily 一样 cache-aside
  - API 优先查 duckdb.volatility_sentiment_daily, 没记录才现算
"""
from __future__ import annotations

import math
import statistics
import time
from datetime import date
from typing import Any

from backend.adapters.market.duckdb_store import get_conn


# 标的固定: 沪深300. 改这个等于换标的, 后续如要扩 (中证1000 / 上证50) 加分支即可.
DEFAULT_UNDERLYING = {
    "code": "000300",
    "name": "沪深300",
    "full": "sh000300",
}

# 窗口 & 历史分位窗口 (默认 20 / 252, 跟 AKShare / Wind 默认一致)
DEFAULT_VOL_WINDOW = 20
DEFAULT_VOL_LOOKBACK = 252

# 一次 SQL 拉多少行 (lookback + window + 10 留 buffer), 防止 500 LIMIT 卡到
_DEFAULT_PULL_LIMIT = 600


def _to_date(v: date | str | None) -> date | None:
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(v)


# ---------------------------------------------------------------------------
# 1. 拉 close 序列
# ---------------------------------------------------------------------------

def _load_closes(
    full_code: str,
    td: date,
    n: int = _DEFAULT_PULL_LIMIT,
) -> list[tuple[date, float]]:
    """从 index_daily_raw 拉 <= td 的最近 n 个交易日 K 线 (升序)."""
    con = get_conn()
    rows = con.execute(
        """
        SELECT trade_date, close
          FROM index_daily_raw
         WHERE code = ? AND trade_date <= ?
         ORDER BY trade_date DESC
         LIMIT ?
        """,
        [full_code, td, n],
    ).fetchall()
    return [(r[0], float(r[1])) for r in reversed(rows)]


# ---------------------------------------------------------------------------
# 2. 算 realized_vol + percentile
# ---------------------------------------------------------------------------

def _realized_vol(returns: list[float], window: int) -> float:
    """std(last `window` returns) × √252 × 100 → 年化波动率 %."""
    if len(returns) < window:
        return float("nan")
    seg = returns[-window:]
    sd = statistics.stdev(seg) if len(seg) >= 2 else 0.0
    return sd * math.sqrt(252) * 100


def _percentile_rank(current: float, history: list[float]) -> float:
    """current 在 history 中的分位数 rank (含等于). 历史空返 0.5."""
    if not history:
        return 0.5
    n_le = sum(1 for v in history if v <= current)
    return n_le / len(history)


# ---------------------------------------------------------------------------
# 3. 主入口: calc_volatility_sentiment
# ---------------------------------------------------------------------------

def calc_volatility_sentiment(
    trade_date: date | str,
    *,
    underlying: dict[str, str] | None = None,
    window: int = DEFAULT_VOL_WINDOW,
    lookback: int = DEFAULT_VOL_LOOKBACK,
) -> dict[str, Any] | None:
    """在 trade_date 算波动率情绪 (沪深300 = 默认 underlying).

    Returns dict (字段跟表结构 1:1, 多 tradeDate / fromCache=False):
      {
        "tradeDate": "2026-06-16",
        "underlyingCode": "sh000300",
        "underlyingName": "沪深300",
        "close": 3850.12,
        "dailyReturnPct": 0.42,        # 当日日收益率 %
        "realizedVol20d": 18.42,       # 20 日年化波动率 %
        "volWindowDays": 20,
        "volLookbackDays": 252,
        "percentile1y": 0.625,         # 0-1, 越小=越平静
        "sentimentScore": 37.5,        # 0-100, 反向 (高分=情绪好)
        "sampleCount": 252,            # 历史分位用到的样本数
        "elapsedMs": 12,
        "source": "duckdb.index_daily_raw",
      }
      数据不足返 None (不抛).
    """
    td = _to_date(trade_date)
    if td is None:
        return None
    u = underlying or DEFAULT_UNDERLYING
    window = max(2, min(window, 60))
    lookback = max(window + 1, min(lookback, 1000))

    t0 = time.time()
    bars = _load_closes(u["full"], td, n=lookback + window + 10)
    # 至少要 window+1 根 (算 1 个 vol); 至少要 2 根才能算 std
    if len(bars) < window + 2:
        return None

    closes = [c for _, c in bars]
    dates = [d for d, _ in bars]

    # 日收益率序列: returns[i] 对应 dates[i+1] 当日收益
    returns: list[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        cur = closes[i]
        r = (cur - prev) / prev if prev > 0 else 0.0
        returns.append(r)

    # 各日 vol 序列: vol[k] 对应 dates[k+window] 当日的 vol (用了 window 个 returns)
    # 也就是 dates[window], dates[window+1], ..., dates[-1] 都各自有一个 vol
    vol_series: list[tuple[date, float]] = []
    for k in range(window, len(closes)):
        seg = returns[k - window:k]
        if len(seg) < 2:
            continue
        sd = statistics.stdev(seg)
        vol_series.append((dates[k], sd * math.sqrt(252) * 100))

    if not vol_series:
        return None

    # td 必须有 vol (要 td ∈ vol_series)
    if vol_series[-1][0] != td:
        # td 没在 index_daily_raw 收盘后, 落库延后 (17:00 之后才有)
        return None

    current_date, current_vol = vol_series[-1]

    # 历史样本 = 过去 lookback 天 (不含今天)
    if len(vol_series) >= lookback + 1:
        sample = [v for _, v in vol_series[-lookback - 1:-1]]
    else:
        sample = [v for _, v in vol_series[:-1]]
    sample_count = len(sample)

    percentile = _percentile_rank(current_vol, sample)
    score = round((1.0 - percentile) * 100.0, 2)
    realized_vol = round(current_vol, 2)
    percentile_rounded = round(percentile, 4)

    daily_return_pct = round(returns[-1] * 100.0, 4) if returns else None
    close_today = round(closes[-1], 4)

    elapsed_ms = int((time.time() - t0) * 1000)
    return {
        "tradeDate": current_date.isoformat(),
        "underlyingCode": u["full"],
        "underlyingName": u["name"],
        "close": close_today,
        "dailyReturnPct": daily_return_pct,
        "realizedVol20d": realized_vol,
        "volWindowDays": window,
        "volLookbackDays": lookback,
        "percentile1y": percentile_rounded,
        "sentimentScore": score,
        "sampleCount": sample_count,
        "elapsedMs": elapsed_ms,
        "source": "duckdb.index_daily_raw",
    }


# ---------------------------------------------------------------------------
# 4. 落盘 + 读
# ---------------------------------------------------------------------------

def save_volatility_sentiment(payload: dict) -> None:
    """把 calc_volatility_sentiment 的 dict 落盘 (INSERT OR REPLACE by trade_date)."""
    td = _to_date(payload.get("tradeDate"))
    if td is None:
        raise ValueError("payload.tradeDate required")
    daily_ret = payload.get("dailyReturnPct")
    con = get_conn()
    con.execute("""
        INSERT OR REPLACE INTO volatility_sentiment_daily
            (trade_date, underlying_code, underlying_name, close, daily_return_pct,
             realized_vol_20d, vol_window_days, vol_lookback_days,
             percentile_1y, sentiment_score, sample_count,
             elapsed_ms, source, ingested_at)
        VALUES (?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, current_timestamp)
    """, [
        td,
        str(payload.get("underlyingCode") or ""),
        str(payload.get("underlyingName") or ""),
        float(payload.get("close") or 0),
        float(daily_ret) if daily_ret is not None else None,
        float(payload.get("realizedVol20d") or 0),
        int(payload.get("volWindowDays") or DEFAULT_VOL_WINDOW),
        int(payload.get("volLookbackDays") or DEFAULT_VOL_LOOKBACK),
        float(payload.get("percentile1y") or 0),
        float(payload.get("sentimentScore") or 0),
        int(payload.get("sampleCount") or 0),
        int(payload.get("elapsedMs") or 0),
        str(payload.get("source") or "duckdb.index_daily_raw"),
    ])


_VOL_SENTIMENT_COLS = (
    "trade_date", "underlying_code", "underlying_name", "close", "daily_return_pct",
    "realized_vol_20d", "vol_window_days", "vol_lookback_days",
    "percentile_1y", "sentiment_score", "sample_count",
    "elapsed_ms", "source",
)
_VOL_SENTIMENT_SELECT = ", ".join(_VOL_SENTIMENT_COLS)


def _row_to_payload(row: tuple) -> dict:
    daily_ret = float(row[4]) if row[4] is not None else None
    return {
        "tradeDate": row[0].isoformat(),
        "underlyingCode": str(row[1]),
        "underlyingName": str(row[2]),
        "close": float(row[3]) if row[3] is not None else None,
        "dailyReturnPct": daily_ret,
        "realizedVol20d": float(row[5]) if row[5] is not None else None,
        "volWindowDays": int(row[6]) if row[6] is not None else DEFAULT_VOL_WINDOW,
        "volLookbackDays": int(row[7]) if row[7] is not None else DEFAULT_VOL_LOOKBACK,
        "percentile1y": float(row[8]) if row[8] is not None else None,
        "sentimentScore": float(row[9]) if row[9] is not None else None,
        "sampleCount": int(row[10]) if row[10] is not None else 0,
        "elapsedMs": int(row[11]) if row[11] is not None else None,
        "source": str(row[12]),
        "fromCache": True,
    }


def get_volatility_sentiment(trade_date: date | str) -> dict | None:
    """按日期查 volatility_sentiment_daily. 无记录返 None (不抛)."""
    td = _to_date(trade_date)
    if td is None:
        return None
    con = get_conn()
    r = con.execute(
        f"SELECT {_VOL_SENTIMENT_SELECT} FROM volatility_sentiment_daily WHERE trade_date = ?",
        [td],
    ).fetchone()
    return _row_to_payload(r) if r else None


def get_volatility_sentiment_history(
    start: date | str,
    end: date | str | None = None,
) -> list[dict]:
    """区间查 volatility_sentiment_daily (按 trade_date ASC)."""
    s = _to_date(start)
    e = _to_date(end) if end is not None else s
    if s is None or e is None:
        return []
    con = get_conn()
    rows = con.execute(
        f"SELECT {_VOL_SENTIMENT_SELECT} FROM volatility_sentiment_daily "
        f"WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date ASC",
        [s, e],
    ).fetchall()
    return [_row_to_payload(r) for r in rows]


def coverage() -> dict[str, Any]:
    """运维用: 第一条 / 最后一条 / 总条数."""
    con = get_conn()
    r = con.execute(
        "SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM volatility_sentiment_daily"
    ).fetchone()
    return {
        "firstDate": r[0].isoformat() if r[0] else None,
        "lastDate": r[1].isoformat() if r[1] else None,
        "rowCount": int(r[2]) if r[2] else 0,
    }


# ---------------------------------------------------------------------------
# 5. cache-aside
# ---------------------------------------------------------------------------

def calc_volatility_sentiment_cached(
    trade_date: date | str,
    *,
    underlying: dict[str, str] | None = None,
    window: int = DEFAULT_VOL_WINDOW,
    lookback: int = DEFAULT_VOL_LOOKBACK,
    force: bool = False,
) -> dict | None:
    """cache-aside 版: 优先查 volatility_sentiment_daily, 没记录才现算 + 自动落盘.

    Args:
        trade_date: 目标日
        window: vol 窗口 (默认 20)
        lookback: 历史分位窗口 (默认 252)
        force: True 跳过 cache 重算 + 覆盖 (调算法 / 修复数据后)
    """
    if not force:
        cached = get_volatility_sentiment(trade_date)
        if cached is not None:
            return cached
    payload = calc_volatility_sentiment(
        trade_date, underlying=underlying, window=window, lookback=lookback,
    )
    if payload is None:
        return None
    try:
        save_volatility_sentiment(payload)
    except Exception:
        pass
    return payload


# ---------------------------------------------------------------------------
# smoke
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json as _json
    print("=== coverage ===")
    print(_json.dumps(coverage(), indent=2, ensure_ascii=False))
    print("\n=== calc_volatility_sentiment(2026-06-16) ===")
    print(_json.dumps(calc_volatility_sentiment("2026-06-16"), indent=2, ensure_ascii=False))
