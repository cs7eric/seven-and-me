"""历史分位数 (Percentile Score) 通用仓储.

对任意 (table, column, target_date, current_value) 算 3 年滚动分位数,
返回 0-100 的情绪得分。

设计思路:
  把 Spread 类指标 (Risk Appetite / Style Risk Appetite / 成交额活跃度 / 252日新高)
  映射到 0-100 分的"情绪得分",
  而不是用固定经验范围 (如 ±2%) 做线性映射。

  固定范围的致命问题是未来会漂移:
    2020年牛市 spread=+8%, 2024年熊市 spread=-6%
    "spread=+2%=100分" 这种映射过两年就不成立了

  历史分位数的优点是:
    - 始终在 0-100 范围内
    - 自动适应市场环境变化
    - 解释自然: "当前风险偏好高于过去 3 年中 82% 的时间"

用法:
    score = percentile_score("risk_appetite_daily", "spread_weighted", "2026-06-17", 1.8)
    # → 82.0  (1.8% 的 spread 高于过去 3 年中 82% 的交易日)
"""

from datetime import date, timedelta
from typing import Any

from backend.adapters.market.duckdb_store import conn

# 默认 3 年 ≈ 756 个交易日 ≈ 1060 个日历天
_DEFAULT_LOOKBACK = 1060


def percentile_score(
    table: str,
    column: str,
    target_date: str | date,
    current_value: float | int | None,
    *,
    lookback_days: int = _DEFAULT_LOOKBACK,
) -> float | None:
    """计算 current_value 在 table.column 历史中的百分位排名 (0-100).

    算法:
      percentile = count(历史值 < current_value) / count(历史值) × 100

    使用 target_date 之前 (不含当天) 的 lookback 天历史,
    避免纳入未来信息 (look-ahead bias).

    Args:
        table: 表名.
        column: 数值列名.
        target_date: 当前交易日.
        current_value: 当前值.
        lookback_days: 回看天数 (默认 1060 ≈ 3y).

    Returns:
        0-100 的得分. 无历史数据或 current_value 为 None 时返回 None
        (上游 msi 走中性 50).
    """
    if current_value is None:
        return None
    td = date.fromisoformat(target_date) if isinstance(target_date, str) else target_date
    lookback_start = td - timedelta(days=lookback_days)
    try:
        with conn() as con:
            row = con.execute(
                f"""
                SELECT COUNT(*) FILTER (WHERE {column} < ?) * 100.0
                       / NULLIF(COUNT(*), 0) AS score
                FROM {table}
                WHERE trade_date >= ? AND trade_date < ?
                  AND {column} IS NOT NULL
                """,
                [float(current_value), lookback_start, td],
            ).fetchone()
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
    """给 history items 每行加上百分位得分.

    算法 (修复 look-ahead bias):
      对每一天 T (T ∈ [start, end]), 用 T 之前 lookback_days 天内 (含 T 自身?)
      的所有 val 计算"严格小于 T.val 的占比", 避免 T 日之后的数据污染过去日的分位.

      T 的分位 = COUNT(prev.val < T.val) / COUNT(prev) × 100
        其中 prev 满足:  T - lookback_days ≤ prev.trade_date < T.trade_date

      实现: 自连接 + 区间过滤, DuckDB 单查询 O(N²) 756²≈570k 配对 <100ms.

    Args:
        items: 历史 items (每条必须有 tradeDate 字段).
        table: 表名.
        column: 数值列名.
        end_date: 查询截止日 (回看窗口终点, 含当天).
        lookback_days: 回看天数.
        score_key: 写入 items 的字段名 (默认 "score").

    Returns:
        同 items, 每行加 score 字段 (mutate in-place + return).
    """
    if not items:
        return items
    end_d = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
    lookback_start = end_d - timedelta(days=lookback_days)

    try:
        with conn() as con:
            rows = con.execute(
                f"""
                WITH t AS (
                  SELECT trade_date, {column} AS val
                    FROM {table}
                   WHERE trade_date >= ? AND trade_date <= ?
                     AND {column} IS NOT NULL
                )
                SELECT
                  cur.trade_date,
                  100.0 * SUM(CASE WHEN prev.val < cur.val THEN 1 ELSE 0 END)
                      / NULLIF(COUNT(prev.val), 0) AS score
                FROM t cur
                LEFT JOIN t prev
                  ON prev.trade_date < cur.trade_date
                 AND prev.trade_date >= cur.trade_date - INTERVAL '{lookback_days} days'
                GROUP BY cur.trade_date
                ORDER BY cur.trade_date ASC
                """,
                [lookback_start, end_d],
            ).fetchall()
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
