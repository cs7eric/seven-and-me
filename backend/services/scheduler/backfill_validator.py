"""CH/PG 回填数据校验工具.

所有 backfill scheduler job 在 subprocess / repo 计算成功后, 必须额外校验:
  1. 目标日期在目标表中有数据 (NOT NULL)
  2. 值不为 0 (0 通常是计算异常/空数据)

校验失败 → 标记 job 为 failed.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy import text

from backend.adapters.market.clickhouse_store import query_one
from backend.config.database import session_scope
from backend.repositories.market.market_pg_cynexus_repo import qname, to_date

logger = logging.getLogger(__name__)

_PG_TABLE_MAP = {
    "market_overview_daily": "mkt_overview_daily",
    "market_pulse_sector_daily": "mkt_sector_pulse_daily",
    "ma_count_daily": "msi_ma_count_daily",
    "index_returns_daily": "mkt_index_return_daily",
    "risk_appetite_daily": "msi_risk_appetite_daily",
    "style_risk_appetite_daily": "msi_style_risk_daily",
    "turnover_activity_daily": "msi_turnover_activity_daily",
    "volatility_sentiment_daily": "msi_volatility_daily",
    "sector_breadth_daily": "msi_sector_breadth_daily",
    "market_pulse_sector_breadth_daily": "msi_sector_breadth_daily",
    "profit_effect_daily": "msi_profit_effect_daily",
    "market_sentiment_index_daily": "msi_index_daily",
    "limit_emotion_summary_daily": "msi_limit_emotion_daily",
    "ths_industry_fund_flow_daily": "mkt_ths_industry_fund_flow_daily",
}

_CH_TABLES = {
    "daily_raw",
    "daily_qfq",
    "daily_hfq",
    "index_daily_raw",
    "intraday_bars",
    "quotes",
}


def _ident(name: str) -> str:
    if not name.replace("_", "").isalnum():
        raise ValueError(f"invalid identifier: {name!r}")
    return name


def _normalize_date(value: date | str) -> date:
    td = to_date(value)
    if td is None:
        raise ValueError("target_date required")
    return td


def _pg_table(table: str) -> str | None:
    if table.startswith("cynexus_appl_market."):
        return table.split(".", 1)[1]
    mapped = _PG_TABLE_MAP.get(table, table)
    if mapped in _CH_TABLES:
        return None
    return mapped


def _is_ch_table(table: str) -> bool:
    return table in _CH_TABLES or table.startswith("cynexus.")


def _row_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if hasattr(value, "date"):
        return value.date()
    return date.fromisoformat(str(value))


def resolve_latest_count_date(table: str, target_date: date | str, min_rows: int = 1) -> date | None:
    """返回 table 中 <= target_date 且行数 >= min_rows 的最近 trade_date."""
    try:
        td = _normalize_date(target_date)
        if _is_ch_table(table):
            table_name = _ident(table.split(".", 1)[-1])
            row = query_one(
                f"""
                SELECT trade_date
                  FROM {table_name}
                 WHERE trade_date <= %s
                 GROUP BY trade_date
                HAVING count() >= %s
                 ORDER BY trade_date DESC
                 LIMIT 1
                """,
                (td, min_rows),
            )
        else:
            table_name = _pg_table(table)
            assert table_name is not None
            row = None
            with session_scope() as db:
                row = db.execute(
                    text(
                        f"""
                        SELECT trade_date
                          FROM {qname(table_name)}
                         WHERE trade_date <= :target_date
                           AND deleted_at IS NULL
                         GROUP BY trade_date
                        HAVING COUNT(*) >= :min_rows
                         ORDER BY trade_date DESC
                         LIMIT 1
                        """
                    ),
                    {"target_date": td, "min_rows": min_rows},
                ).first()
    except Exception as exc:
        logger.warning("resolve_latest_count_date(%s, %s) failed: %s", table, target_date, exc)
        return None
    if not row or row[0] is None:
        return None
    return _row_date(row[0])


def resolve_latest_scalar_date(table: str, column: str, target_date: date | str) -> date | None:
    """返回 table 中 <= target_date 且 column 非 NULL 且 != 0 的最近 trade_date."""
    try:
        td = _normalize_date(target_date)
        col = _ident(column)
        if _is_ch_table(table):
            table_name = _ident(table.split(".", 1)[-1])
            row = query_one(
                f"""
                SELECT trade_date
                  FROM {table_name}
                 WHERE trade_date <= %s
                   AND {col} IS NOT NULL
                   AND toFloat64({col}) != 0
                 ORDER BY trade_date DESC
                 LIMIT 1
                """,
                (td,),
            )
        else:
            table_name = _pg_table(table)
            assert table_name is not None
            row = None
            with session_scope() as db:
                row = db.execute(
                    text(
                        f"""
                        SELECT trade_date
                          FROM {qname(table_name)}
                         WHERE trade_date <= :target_date
                           AND {col} IS NOT NULL
                           AND CAST({col} AS DOUBLE PRECISION) <> 0
                           AND deleted_at IS NULL
                         GROUP BY trade_date
                         ORDER BY trade_date DESC
                         LIMIT 1
                        """
                    ),
                    {"target_date": td},
                ).first()
    except Exception as exc:
        logger.warning(
            "resolve_latest_scalar_date(%s.%s, %s) failed: %s",
            table, column, target_date, exc,
        )
        return None
    if not row or row[0] is None:
        return None
    return _row_date(row[0])


def validate_scalar(table: str, column: str, target_date: date | str) -> tuple[bool, str | None]:
    """校验 CH/PG 表的目标日期行有一列不为 NULL 且 != 0."""
    try:
        td = _normalize_date(target_date)
        col = _ident(column)
        if _is_ch_table(table):
            table_name = _ident(table.split(".", 1)[-1])
            row = query_one(f"SELECT {col} FROM {table_name} WHERE trade_date = %s LIMIT 1", (td,))
        else:
            table_name = _pg_table(table)
            assert table_name is not None
            with session_scope() as db:
                row = db.execute(
                    text(f"SELECT {col} FROM {qname(table_name)} WHERE trade_date = :target_date AND deleted_at IS NULL LIMIT 1"),
                    {"target_date": td},
                ).first()
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
    """读取 CH/PG 表在 target_date 的标量值, 返回 float 或 None."""
    try:
        td = _normalize_date(target_date)
        col = _ident(column)
        if _is_ch_table(table):
            table_name = _ident(table.split(".", 1)[-1])
            row = query_one(f"SELECT {col} FROM {table_name} WHERE trade_date = %s LIMIT 1", (td,))
        else:
            table_name = _pg_table(table)
            assert table_name is not None
            with session_scope() as db:
                row = db.execute(
                    text(f"SELECT {col} FROM {qname(table_name)} WHERE trade_date = :target_date AND deleted_at IS NULL LIMIT 1"),
                    {"target_date": td},
                ).first()
        if row and row[0] is not None:
            return float(row[0])
        return None
    except Exception as exc:
        logger.debug("fetch_scalar_value(%s.%s, %s) failed: %s", table, column, target_date, exc)
        return None


def validate_count(table: str, target_date: date | str, min_rows: int = 1) -> tuple[bool, str | None]:
    """校验 CH/PG 表的目标日期至少有 min_rows 行."""
    try:
        td = _normalize_date(target_date)
        if _is_ch_table(table):
            table_name = _ident(table.split(".", 1)[-1])
            row = query_one(f"SELECT count() FROM {table_name} WHERE trade_date = %s", (td,))
        else:
            table_name = _pg_table(table)
            assert table_name is not None
            with session_scope() as db:
                row = db.execute(
                    text(f"SELECT COUNT(*) FROM {qname(table_name)} WHERE trade_date = :target_date AND deleted_at IS NULL"),
                    {"target_date": td},
                ).first()
    except Exception as exc:
        msg = f"{table} COUNT query failed: {exc}"
        logger.warning(msg)
        return False, msg

    if not row or int(row[0]) < min_rows:
        msg = f"{table} has {row[0] if row else 0} rows for {target_date} (expected >= {min_rows})"
        logger.warning(msg)
        return False, msg

    return True, None
