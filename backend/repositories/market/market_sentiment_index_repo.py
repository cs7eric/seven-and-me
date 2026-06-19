"""市场情绪指数 (Market Sentiment Index) 仓储.

公式 (v1.0):
  composite_score = 15% × 波动率情绪
                 + 15% × 成交活跃度
                 + 10% × 价格强度 (252 日新高分位)
                 + 10% × 风险偏好
                 + 15% × 市场广度
                 + 15% × 涨跌停情绪
                 + 10% × 赚钱效应
                 +  5% × 板块扩散
                 +  5% × 风格风险偏好

所有 component score 0-100, composite_score 0-100.
数据缺失的 component 视为 50 (中性), 不影响整张卡显示.

数据源: 各 *_daily 子表 (cache-aside, 已由各 scheduler / backfill 落盘)
  - volatility_sentiment_daily.sentiment_score      (反向, 高分=平静)
  - turnover_activity_daily.score                  (历史分位, 高分=放量)
  - ma_count_daily.new_high_252d_pct               → 百分位
  - risk_appetite_daily.spread_weighted            → 百分位
  - ma_count_daily 综合 (40%上涨 + 35%MA20 + 25%MA60)
  - limit_emotion_summary_daily.composite_score
  - profit_effect_daily.score
  - market_pulse_sector_breadth_daily.advance_pct  → ×100
  - style_risk_appetite_daily.spread               → 百分位

落盘: duckdb.market_sentiment_index_daily (INSERT OR REPLACE by trade_date)
读模式: cache-aside — API 优先查表, 无记录才现算
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

from backend.adapters.market.duckdb_store import get_conn
from backend.repositories.market.percentile_helper import percentile_score
from backend.services.stock.trading_calendar import is_trading_day

logger = logging.getLogger(__name__)


# 9 个 component 的权重 (合计 1.00)
WEIGHTS: dict[str, float] = {
    "vol": 0.15,
    "turnover": 0.15,
    "price_strength": 0.10,
    "risk_appetite": 0.10,
    "breadth": 0.15,
    "limit_emotion": 0.15,
    "profit_effect": 0.10,
    "sector_breadth": 0.05,
    "style_risk": 0.05,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "weights must sum to 1.0"


# 缺失 component 的中性分
_MISSING_SCORE = 50.0


def _to_date(v: date | str | None) -> date | None:
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(v)


def _level(score: float) -> str:
    """0-100 → 等级."""
    if score >= 70:
        return "hot"
    if score >= 55:
        return "active"
    if score >= 45:
        return "normal"
    if score >= 30:
        return "weak"
    return "ice"


# ---------------------------------------------------------------------------
# 1. 计算 component scores (各 0-100)
# ---------------------------------------------------------------------------

def _fetch_vol_score(td: date) -> float | None:
    """波动率情绪: 来自 volatility_sentiment_daily.sentiment_score."""
    con = get_conn()
    r = con.execute(
        "SELECT sentiment_score FROM volatility_sentiment_daily WHERE trade_date = ?",
        [td],
    ).fetchone()
    if r and r[0] is not None:
        return round(float(r[0]), 2)
    return None


def _fetch_turnover_score(td: date) -> float | None:
    """成交活跃度: 来自 turnover_activity_daily.score (历史分位, 已落盘).

    兜底: 旧数据 score 为 NULL 时, 用 ratio 现算 percentile (跟 turnover_repo._add_score 同口径).
    """
    con = get_conn()
    r = con.execute(
        "SELECT score, ratio FROM turnover_activity_daily WHERE trade_date = ?",
        [td],
    ).fetchone()
    if not r:
        return None
    score, ratio = r
    if score is not None:
        return round(float(score), 2)
    if ratio is None:
        return None
    return percentile_score("turnover_activity_daily", "ratio", td, float(ratio))


def _fetch_price_strength_score(td: date) -> float | None:
    """价格强度: ma_count_daily.new_high_252d_pct → 历史分位."""
    con = get_conn()
    r = con.execute(
        "SELECT new_high_252d_pct FROM ma_count_daily WHERE trade_date = ?",
        [td],
    ).fetchone()
    if not r or r[0] is None:
        return None
    return percentile_score("ma_count_daily", "new_high_252d_pct", td, float(r[0]))


def _fetch_risk_appetite_score(td: date) -> float | None:
    """风险偏好: risk_appetite_daily.spread_weighted → 历史分位."""
    con = get_conn()
    r = con.execute(
        "SELECT spread_weighted FROM risk_appetite_daily WHERE trade_date = ?",
        [td],
    ).fetchone()
    if not r or r[0] is None:
        return None
    return percentile_score("risk_appetite_daily", "spread_weighted", td, float(r[0]))


def _fetch_breadth_score(td: date) -> float | None:
    """市场广度: ma_count_daily.breadth_raw (40%上涨 + 35%MA20 + 25%MA60 合成) → 历史分位."""
    con = get_conn()
    r = con.execute(
        "SELECT breadth_raw FROM ma_count_daily WHERE trade_date = ?",
        [td],
    ).fetchone()
    if not r or r[0] is None:
        return None
    return percentile_score("ma_count_daily", "breadth_raw", td, float(r[0]))


def _fetch_limit_emotion_score(td: date) -> float | None:
    """涨跌停情绪: limit_emotion_summary_daily.composite_score (0-100)."""
    con = get_conn()
    r = con.execute(
        "SELECT composite_score FROM limit_emotion_summary_daily WHERE trade_date = ?",
        [td],
    ).fetchone()
    if r and r[0] is not None:
        return round(float(r[0]), 2)
    return None


def _fetch_profit_effect_score(td: date) -> float | None:
    """赚钱效应: profit_effect_daily.score (公式 raw) → 历史分位.

    score 存的是 0.6*up5d + 0.4*(100-newlow60d) 的 0-100 合成,
    msi 跟其他 8 factor 一样取 (T-3y, T) 滚动分位.
    """
    con = get_conn()
    r = con.execute(
        "SELECT score FROM profit_effect_daily WHERE trade_date = ?",
        [td],
    ).fetchone()
    if not r or r[0] is None:
        return None
    return percentile_score("profit_effect_daily", "score", td, float(r[0]))


def _fetch_sector_breadth_score(td: date) -> float | None:
    """板块扩散: market_pulse_sector_breadth_daily.advance_pct × 100."""
    con = get_conn()
    r = con.execute(
        "SELECT advance_pct FROM market_pulse_sector_breadth_daily WHERE trade_date = ?",
        [td],
    ).fetchone()
    if r and r[0] is not None:
        return round(float(r[0]) * 100, 2)
    return None


def _fetch_style_risk_score(td: date) -> float | None:
    """风格风险偏好: style_risk_appetite_daily.spread → 历史分位."""
    con = get_conn()
    r = con.execute(
        "SELECT spread FROM style_risk_appetite_daily WHERE trade_date = ?",
        [td],
    ).fetchone()
    if not r or r[0] is None:
        return None
    return percentile_score("style_risk_appetite_daily", "spread", td, float(r[0]))


_COMPONENT_FETCHERS = {
    "vol": _fetch_vol_score,
    "turnover": _fetch_turnover_score,
    "price_strength": _fetch_price_strength_score,
    "risk_appetite": _fetch_risk_appetite_score,
    "breadth": _fetch_breadth_score,
    "limit_emotion": _fetch_limit_emotion_score,
    "profit_effect": _fetch_profit_effect_score,
    "sector_breadth": _fetch_sector_breadth_score,
    "style_risk": _fetch_style_risk_score,
}


# ---------------------------------------------------------------------------
# 2. calc
# ---------------------------------------------------------------------------

def calc_market_sentiment_index(trade_date: date | str) -> dict[str, Any] | None:
    """在 trade_date 算市场情绪指数 (9 张卡加权合成).

    Returns:
      {
        "tradeDate",
        "components": {vol, turnover, ..., style_risk},   # 0-100, None=缺失
        "compositeScore": 0-100,
        "componentCount": int (1-9),
        "level": hot/active/normal/weak/ice,
        "weights": {...},  # 9 个权重
        "elapsedMs",
        "source": "composite"
      }
      全 9 个 component 都缺失时返 None (避免误传).
    """
    td = _to_date(trade_date)
    if td is None:
        return None
    t0 = time.time()

    components: dict[str, float | None] = {}
    for key, fetcher in _COMPONENT_FETCHERS.items():
        try:
            components[key] = fetcher(td)
        except Exception as exc:
            logger.debug("component %s fetch failed for %s: %s", key, td, exc)
            components[key] = None

    # 缺失视为 50 (中性), 仍然参与合成 (避免 0 拖低分); 记 component_count 用于审计
    present = [k for k, v in components.items() if v is not None]
    if not present:
        return None

    composite = 0.0
    for key, weight in WEIGHTS.items():
        score = components[key] if components[key] is not None else _MISSING_SCORE
        composite += weight * score
    composite = round(composite, 2)

    elapsed_ms = int((time.time() - t0) * 1000)
    return {
        "tradeDate": td.isoformat(),
        "components": components,
        "compositeScore": composite,
        "componentCount": len(present),
        "level": _level(composite),
        "weights": dict(WEIGHTS),
        "elapsedMs": elapsed_ms,
        "source": "composite",
    }


# ---------------------------------------------------------------------------
# 3. 落盘
# ---------------------------------------------------------------------------

def save_market_sentiment_index(payload: dict) -> None:
    """把 calc_market_sentiment_index 的 dict 落盘 (INSERT OR REPLACE by trade_date).

    非交易日直接拒绝落盘 (msi 是工作日指数, 周末/节假日不该有行;
    历史上有子卡周末脏数据污染 msi union → chart SH 叠加线断点的 bug, 见 git log).
    """
    td = _to_date(payload.get("tradeDate"))
    if td is None:
        raise ValueError("payload.tradeDate required")
    if not is_trading_day(td):
        logger.debug("save_market_sentiment_index skipped non-trading day: %s", td)
        return
    components = payload.get("components") or {}

    def _f(key: str) -> float | None:
        v = components.get(key)
        return float(v) if v is not None else None

    con = get_conn()
    con.execute("""
        INSERT OR REPLACE INTO market_sentiment_index_daily
            (trade_date,
             vol_score, turnover_score, price_strength_score,
             risk_appetite_score, breadth_score, limit_emotion_score,
             profit_effect_score, sector_breadth_score, style_risk_score,
             composite_score, component_count, level,
             elapsed_ms, source, ingested_at)
        VALUES (?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, current_timestamp)
    """, [
        td,
        _f("vol"),
        _f("turnover"),
        _f("price_strength"),
        _f("risk_appetite"),
        _f("breadth"),
        _f("limit_emotion"),
        _f("profit_effect"),
        _f("sector_breadth"),
        _f("style_risk"),
        float(payload.get("compositeScore") or 0),
        int(payload.get("componentCount") or 0),
        str(payload.get("level") or "normal"),
        int(payload.get("elapsedMs") or 0),
        str(payload.get("source") or "composite"),
    ])


# ---------------------------------------------------------------------------
# 4. 读
# ---------------------------------------------------------------------------

_MSI_COLS = (
    "trade_date",
    "vol_score", "turnover_score", "price_strength_score",
    "risk_appetite_score", "breadth_score", "limit_emotion_score",
    "profit_effect_score", "sector_breadth_score", "style_risk_score",
    "composite_score", "component_count", "level",
    "elapsed_ms", "source",
)
_MSI_SELECT = ", ".join(_MSI_COLS)


def _row_to_payload(row: tuple) -> dict:
    def _f(i: int) -> float | None:
        v = row[i]
        return float(v) if v is not None else None

    components = {
        "vol": _f(1),
        "turnover": _f(2),
        "price_strength": _f(3),
        "risk_appetite": _f(4),
        "breadth": _f(5),
        "limit_emotion": _f(6),
        "profit_effect": _f(7),
        "sector_breadth": _f(8),
        "style_risk": _f(9),
    }
    return {
        "tradeDate": row[0].isoformat(),
        "components": components,
        "weights": dict(WEIGHTS),
        "compositeScore": float(row[10]) if row[10] is not None else None,
        "componentCount": int(row[11]) if row[11] is not None else 0,
        "level": str(row[12]) if row[12] else "normal",
        "elapsedMs": int(row[13]) if row[13] is not None else None,
        "source": str(row[14]) if row[14] else "composite",
        "fromCache": True,
    }


def get_market_sentiment_index(trade_date: date | str) -> dict | None:
    """按日期查 market_sentiment_index_daily. 无记录返 None (不抛)."""
    td = _to_date(trade_date)
    if td is None:
        return None
    con = get_conn()
    r = con.execute(
        f"SELECT {_MSI_SELECT} FROM market_sentiment_index_daily WHERE trade_date = ?",
        [td],
    ).fetchone()
    return _row_to_payload(r) if r else None


def get_market_sentiment_index_history(
    start: date | str,
    end: date | str | None = None,
) -> list[dict]:
    """区间查 (按 trade_date ASC)."""
    s = _to_date(start)
    e = _to_date(end) if end is not None else s
    if s is None or e is None:
        return []
    con = get_conn()
    rows = con.execute(
        f"SELECT {_MSI_SELECT} FROM market_sentiment_index_daily "
        f"WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date ASC",
        [s, e],
    ).fetchall()
    return [_row_to_payload(r) for r in rows]


# ---------------------------------------------------------------------------
# 5. cache-aside
# ---------------------------------------------------------------------------

def calc_market_sentiment_index_cached(
    trade_date: date | str,
    *,
    force: bool = False,
) -> dict | None:
    """cache-aside: 优先查表, 没记录才现算 + 自动落盘.

    注意: composite 依赖 9 张子卡都落盘, 所以单日 component_count 可能 < 9
    (早期日或子卡 backfill 没覆盖). component_count 在前端用于提示.
    """
    if not force:
        cached = get_market_sentiment_index(trade_date)
        if cached is not None:
            return cached
    payload = calc_market_sentiment_index(trade_date)
    if payload is None:
        return None
    try:
        save_market_sentiment_index(payload)
    except Exception:
        logger.debug(
            "save_market_sentiment_index failed (non-fatal): %s",
            payload.get("tradeDate"),
        )
    return payload


# ---------------------------------------------------------------------------
# smoke
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json as _json
    from backend.adapters.market.duckdb_store import get_conn

    con = get_conn()
    r = con.execute(
        "SELECT MIN(trade_date), MAX(trade_date), COUNT(*) "
        "FROM market_sentiment_index_daily"
    ).fetchone()
    print(f"coverage: first={r[0]} last={r[1]} count={r[2]}")

    print("\n=== calc_market_sentiment_index(2026-06-17) ===")
    p = calc_market_sentiment_index("2026-06-17")
    if p:
        print(_json.dumps(p, indent=2, ensure_ascii=False))
    else:
        print("  no data (sub-tables empty)")

    print("\n=== calc_market_sentiment_index_cached(2026-06-17) ===")
    p = calc_market_sentiment_index_cached("2026-06-17", force=True)
    if p:
        print(_json.dumps(p, indent=2, ensure_ascii=False))
