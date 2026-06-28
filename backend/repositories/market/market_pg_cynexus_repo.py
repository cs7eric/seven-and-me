"""Small PostgreSQL helpers for ``cynexus_appl_market`` market tables.

This module intentionally uses focused SQLAlchemy Core text/insert helpers instead
of broad repository classes.  The migrated tables already exist from external DDL
and most legacy modules need simple cache-aside reads/writes while preserving
module-level function signatures.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session
from psycopg.types.json import Jsonb

from backend.config.database import session_scope
from backend.utils.id_generator import next_id

SCHEMA = "cynexus_appl_market"


def to_date(value: date | str | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def to_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def alive_where(alias: str | None = None) -> str:
    prefix = f"{alias}." if alias else ""
    return f"{prefix}deleted_at IS NULL"


def qname(table: str) -> str:
    if not table.replace("_", "").isalnum():
        raise ValueError(f"invalid table name: {table!r}")
    return f"{SCHEMA}.{table}"


def fetch_one(
    table: str,
    columns: Sequence[str],
    where: str,
    params: Mapping[str, Any],
    *,
    order_by: str | None = None,
) -> dict[str, Any] | None:
    sql = f"SELECT {', '.join(columns)} FROM {qname(table)} WHERE {where} AND deleted_at IS NULL"
    if order_by:
        sql += f" ORDER BY {order_by}"
    sql += " LIMIT 1"
    with session_scope() as db:
        row = db.execute(text(sql), dict(params)).mappings().first()
        return dict(row) if row else None


def fetch_all(
    table: str,
    columns: Sequence[str],
    where: str,
    params: Mapping[str, Any],
    *,
    order_by: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    sql = f"SELECT {', '.join(columns)} FROM {qname(table)} WHERE {where} AND deleted_at IS NULL"
    if order_by:
        sql += f" ORDER BY {order_by}"
    if limit is not None:
        sql += " LIMIT :_limit"
        params = {**params, "_limit": int(limit)}
    with session_scope() as db:
        return [dict(row) for row in db.execute(text(sql), dict(params)).mappings().all()]


def execute_upsert(
    db: Session,
    *,
    table: str,
    key_columns: Sequence[str],
    values: Mapping[str, Any],
    update_columns: Sequence[str] | None = None,
) -> None:
    """Upsert one row by the target table's natural key.

    The DDL uses partial unique indexes with ``WHERE deleted_at IS NULL``, so a
    generic ``ON CONFLICT`` target is awkward.  We instead select the live row by
    natural key, then update or insert.  This matches existing repository style
    and keeps the ID stable.
    """
    if not key_columns:
        raise ValueError("key_columns required")
    now = datetime.now()
    existing_where = " AND ".join(f"{col} = :key_{col}" for col in key_columns)
    key_params = {f"key_{col}": values[col] for col in key_columns}
    existing_id = db.execute(
        text(f"SELECT id FROM {qname(table)} WHERE {existing_where} AND deleted_at IS NULL LIMIT 1"),
        key_params,
    ).scalar_one_or_none()

    cleaned = {k: (Jsonb(v) if isinstance(v, (dict, list)) else v) for k, v in values.items() if v is not None}
    if existing_id is None:
        insert_values = {
            "id": next_id(),
            "created_at": now,
            "updated_at": now,
            **cleaned,
        }
        cols = list(insert_values.keys())
        db.execute(
            text(
                f"INSERT INTO {qname(table)} ({', '.join(cols)}) "
                f"VALUES ({', '.join(':' + c for c in cols)})"
            ),
            insert_values,
        )
        return

    update_cols = list(update_columns) if update_columns is not None else [c for c in cleaned.keys() if c not in key_columns and c != "id"]
    update_cols = [c for c in update_cols if c in cleaned]
    if not update_cols:
        return
    params = {c: cleaned[c] for c in update_cols}
    params["id"] = existing_id
    params["updated_at"] = now
    set_sql = ", ".join([*(f"{c} = :{c}" for c in update_cols), "updated_at = :updated_at"])
    db.execute(text(f"UPDATE {qname(table)} SET {set_sql} WHERE id = :id"), params)


def upsert(
    *,
    table: str,
    key_columns: Sequence[str],
    values: Mapping[str, Any],
    update_columns: Sequence[str] | None = None,
) -> None:
    with session_scope() as db:
        execute_upsert(db, table=table, key_columns=key_columns, values=values, update_columns=update_columns)


def coverage(table: str, *, date_column: str = "trade_date") -> dict[str, Any]:
    with session_scope() as db:
        row = db.execute(
            text(
                f"SELECT MIN({date_column}), MAX({date_column}), COUNT(*) "
                f"FROM {qname(table)} WHERE deleted_at IS NULL"
            )
        ).one()
    return {
        "firstDate": row[0].isoformat() if row[0] else None,
        "lastDate": row[1].isoformat() if row[1] else None,
        "rowCount": int(row[2] or 0),
    }


__all__ = [
    "SCHEMA",
    "alive_where",
    "coverage",
    "execute_upsert",
    "fetch_all",
    "fetch_one",
    "qname",
    "session_scope",
    "to_date",
    "to_float",
    "to_int",
    "upsert",
]
