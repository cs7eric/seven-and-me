"""历史分位数 (Percentile Score) 通用仓储 — PostgreSQL backend."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import text

from backend.config.database import session_scope
from backend.repositories.market.market_pg_cynexus_repo import qname

_DEFAULT_LOOKBACK = 1060

_ALLOWED_COLUMNS: dict[str, set[str]] = {
    "ma_count_daily": {"new_high_252d_pct", "breadth_raw", "up_5d_pct", "new_low_60d_pct"},
    "risk_appetite_daily": {"spread_weighted", "spread_511010", "spread_511090"},
    "turnover_activity_daily": {"ratio", "score"},
    "profit_effect_daily": {"score"},
    "style_risk_appetite_daily": {"spread"},
    "limit_emotion_summary_daily": {"limit_up_down_ratio", "break_board_rate", "yesterday_limit_up_avg_return", "composite_score"},
    "volatility_sentiment_daily": {"sentiment_score", "realized_vol_20d", "percentile_1y"},
}

_TABLE_MAP = {
    "ma_count_daily": "msi_ma_count_daily",
    "risk_appetite_daily": "msi_risk_appetite_daily",
    "turnover_activity_daily": "msi_turnover_activity_daily",
    "profit_effect_daily": "msi_profit_effect_daily",
    "style_risk_appetite_daily": "msi_style_risk_daily",
    "limit_emotion_summary_daily": "msi_limit_emotion_daily",
    "volatility_sentiment_daily": "msi_volatility_daily",
}


def _resolve(table: str, column: str) -> tuple[str, str]:
    allowed = _ALLOWED_COLUMNS.get(table)
    if not allowed or column not in allowed:
        raise ValueError(f"unsupported percentile source: {table}.{column}")
    return qname(_TABLE_MAP[table]), column


def percentile_score(
    table: str,
    column: str,
    target_date: str | date,
    current_value: float | int | None,
    *,
    lookback_days: int = _DEFAULT_LOOKBACK,
) -> float | None:
    if current_value is None:
        return None
    td = date.fromisoformat(target_date) if isinstance(target_date, str) else target_date
    lookback_start = td - timedelta(days=lookback_days)
    try:
        table_name, col = _resolve(table, column)
        with session_scope() as db:
            row = db.execute(
                text(f"""
                    SELECT COUNT(*) FILTER (WHERE {col} < :current_value) * 100.0
                           / NULLIF(COUNT(*), 0) AS score
                    FROM {table_name}
                    WHERE trade_date >= :lookback_start AND trade_date < :target_date
                      AND {col} IS NOT NULL
                      AND deleted_at IS NULL
                """),
                {"current_value": float(current_value), "lookback_start": lookback_start, "target_date": td},
            ).one()
        if row and row[0] is not None:
            return round(float(row[0]), 1)
    except Exception:
        pass
    return 50.0


def enrich_history_scores(
    items: list[dict[str, Any]],
    table: str,
    column: str,
    end_date: str | date,
    *,
    lookback_days: int = _DEFAULT_LOOKBACK,
    score_key: str = "score",
) -> list[dict[str, Any]]:
    if not items:
        return items
    end_d = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
    lookback_start = end_d - timedelta(days=lookback_days)

    try:
        table_name, col = _resolve(table, column)
        with session_scope() as db:
            rows = db.execute(
                text(f"""
                    WITH t AS (
                      SELECT trade_date, {col} AS val
                        FROM {table_name}
                       WHERE trade_date >= :lookback_start AND trade_date <= :end_date
                         AND {col} IS NOT NULL
                         AND deleted_at IS NULL
                    )
                    SELECT
                      cur.trade_date,
                      100.0 * SUM(CASE WHEN prev.val < cur.val THEN 1 ELSE 0 END)
                          / NULLIF(COUNT(prev.val), 0) AS score
                    FROM t cur
                    LEFT JOIN t prev
                      ON prev.trade_date < cur.trade_date
                     AND prev.trade_date >= cur.trade_date - (:lookback_days * INTERVAL '1 day')
                    GROUP BY cur.trade_date
                    ORDER BY cur.trade_date ASC
                """),
                {"lookback_start": lookback_start, "end_date": end_d, "lookback_days": lookback_days},
            ).all()
        score_map: dict[str, float] = {
            r[0].isoformat(): round(float(r[1]), 1) if r[1] is not None else 50.0
            for r in rows
        }
    except Exception:
        score_map = {}

    for item in items:
        td_key = item.get("tradeDate") or item.get("trade_date")
        item[score_key] = score_map.get(str(td_key), 50.0) if td_key else 50.0

    return items
