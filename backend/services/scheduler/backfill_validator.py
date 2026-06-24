"""DuckDB 回填数据校验工具.

所有 backfill scheduler job 在 subprocess 成功后, 必须额外校验:
  1. 目标日期在目标表中有数据 (NOT NULL)
  2. 值不为 0 (0 通常是计算异常/空数据)

校验失败 → 标记 job 为 failed.
"""
from __future__ import annotations

import logging
from datetime import date

logger = logging.getLogger(__name__)


def resolve_latest_count_date(table: str, target_date: date | str, min_rows: int = 1) -> date | None:
    """返回 table 中 <= target_date 且行数 >= min_rows 的最近 trade_date."""
    try:
        from backend.adapters.market.duckdb_store import get_conn
        with get_conn(read_only=True) as con:
            row = con.execute(
                f"""
                SELECT trade_date
                  FROM {table}
                 WHERE trade_date <= ?
                 GROUP BY trade_date
                HAVING COUNT(*) >= ?
                 ORDER BY trade_date DESC
                 LIMIT 1
                """,
                [target_date, min_rows],
            ).fetchone()
    except Exception as exc:
        logger.warning("resolve_latest_count_date(%s, %s) failed: %s", table, target_date, exc)
        return None
    if not row or row[0] is None:
        return None
    v = row[0]
    return v.date() if hasattr(v, "date") else v


def resolve_latest_scalar_date(table: str, column: str, target_date: date | str) -> date | None:
    """返回 table 中 <= target_date 且 column 非 NULL 且 != 0 的最近 trade_date."""
    try:
        from backend.adapters.market.duckdb_store import get_conn
        with get_conn(read_only=True) as con:
            row = con.execute(
                f"""
                SELECT trade_date
                  FROM {table}
                 WHERE trade_date <= ?
                   AND {column} IS NOT NULL
                   AND CAST({column} AS DOUBLE) <> 0
                 ORDER BY trade_date DESC
                 LIMIT 1
                """,
                [target_date],
            ).fetchone()
    except Exception as exc:
        logger.warning(
            "resolve_latest_scalar_date(%s.%s, %s) failed: %s",
            table, column, target_date, exc,
        )
        return None
    if not row or row[0] is None:
        return None
    v = row[0]
    return v.date() if hasattr(v, "date") else v


def validate_scalar(table: str, column: str, target_date: date | str) -> tuple[bool, str | None]:
    """校验 DuckDB 表的目标日期行有一列不为 NULL 且 > 0.

    Args:
        table: DuckDB 表名
        column: 要检查的列名
        target_date: 目标交易日

    Returns:
        (ok, error_message). ok=True 表示校验通过.
    """
    try:
        from backend.adapters.market.duckdb_store import get_conn
        with get_conn(read_only=True) as con:
            row = con.execute(
                f"SELECT {column} FROM {table} WHERE trade_date = ?",
                [target_date],
            ).fetchone()
    except Exception as exc:
        msg = f"{table}.{column} query failed: {exc}"
        logger.warning(msg)
        return False, msg

    if not row or row[0] is None:
        msg = f"{table}.{column} IS NULL for {target_date} (data not written)"
        logger.warning(msg)
        return False, msg

    val = float(row[0])
    if val == 0:
        msg = f"{table}.{column} = 0 for {target_date} (likely computation error or empty data)"
        logger.warning(msg)
        return False, msg

    return True, None


def fetch_scalar_value(table: str, column: str, target_date: date | str) -> float | None:
    """读取 DuckDB 表在 target_date 的标量值, 返回 float 或 None.

    用于 success message 中展示具体计算结果.
    """
    try:
        from backend.adapters.market.duckdb_store import get_conn
        with get_conn(read_only=True) as con:
            row = con.execute(
                f"SELECT {column} FROM {table} WHERE trade_date = ?",
                [target_date],
            ).fetchone()
        if row and row[0] is not None:
            return float(row[0])
        return None
    except Exception as exc:
        logger.debug("fetch_scalar_value(%s.%s, %s) failed: %s", table, column, target_date, exc)
        return None


def validate_count(table: str, target_date: date | str, min_rows: int = 1) -> tuple[bool, str | None]:
    """校验 DuckDB 表的目标日期至少有 min_rows 行.

    用于 daily_raw / daily_qfq 等行数校验 (不检查具体值).
    """
    try:
        from backend.adapters.market.duckdb_store import get_conn
        with get_conn(read_only=True) as con:
            row = con.execute(
                f"SELECT COUNT(*) FROM {table} WHERE trade_date = ?",
                [target_date],
            ).fetchone()
    except Exception as exc:
        msg = f"{table} COUNT query failed: {exc}"
        logger.warning(msg)
        return False, msg

    if not row or int(row[0]) < min_rows:
        msg = f"{table} has {row[0] if row else 0} rows for {target_date} (expected >= {min_rows})"
        logger.warning(msg)
        return False, msg

    return True, None
