"""ClickHouse connection helpers for migrated market time-series data.

Runtime market detail tables live in the ClickHouse ``cynexus`` database.  This
module intentionally mirrors :mod:`backend.config.database`: no connection is
opened at import time; env vars are read only when the first query runs.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any, Iterable, Sequence

logger = logging.getLogger(__name__)


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("invalid %s=%r, using default %s", name, value, default)
        return default


@lru_cache(maxsize=1)
def get_client():
    """Return a cached clickhouse-connect client.

    Defaults match the local Docker/JDBC HTTP endpoint from the migration notes.
    Tests/imports can import this module without a live ClickHouse instance.
    """
    import clickhouse_connect

    return clickhouse_connect.get_client(
        host=os.getenv("CLICKHOUSE_HOST", "127.0.0.1"),
        port=_int_env("CLICKHOUSE_PORT", 28123),
        username=os.getenv("CLICKHOUSE_USERNAME", "cynexus"),
        password=os.getenv("CLICKHOUSE_PASSWORD", "C020611."),
        database=os.getenv("CLICKHOUSE_DATABASE", "cynexus"),
        secure=_bool_env("CLICKHOUSE_SECURE", False),
        compress=_bool_env("CLICKHOUSE_COMPRESSION", True),
        connect_timeout=_int_env("CLICKHOUSE_CONNECT_TIMEOUT", 10),
        send_receive_timeout=_int_env("CLICKHOUSE_SEND_RECEIVE_TIMEOUT", 60),
        query_limit=_int_env("CLICKHOUSE_QUERY_LIMIT_DEFAULT", 0),
    )


def close_client() -> None:
    """Close and clear the cached client, mainly for tests/reloads."""
    client = get_client.cache_info().currsize and get_client()
    if client:
        try:
            client.close()
        finally:
            get_client.cache_clear()


def query(sql: str, parameters: dict[str, Any] | Sequence[Any] | None = None, **kwargs: Any):
    """Execute a ClickHouse query and return the clickhouse-connect result."""
    return get_client().query(sql, parameters=parameters, **kwargs)


def query_rows(sql: str, parameters: dict[str, Any] | Sequence[Any] | None = None, **kwargs: Any) -> list[tuple[Any, ...]]:
    """Execute a SELECT and return row tuples."""
    return list(query(sql, parameters=parameters, **kwargs).result_rows)


def query_one(sql: str, parameters: dict[str, Any] | Sequence[Any] | None = None, **kwargs: Any) -> tuple[Any, ...] | None:
    """Execute a SELECT and return the first row, if any."""
    rows = query_rows(sql, parameters=parameters, **kwargs)
    return rows[0] if rows else None


def command(sql: str, parameters: dict[str, Any] | Sequence[Any] | None = None, **kwargs: Any) -> Any:
    """Execute a non-SELECT command."""
    return get_client().command(sql, parameters=parameters, **kwargs)


def insert(
    table: str,
    rows: Sequence[Sequence[Any]],
    column_names: Sequence[str],
    *,
    database: str | None = None,
    column_type_names: Sequence[str] | None = None,
    settings: dict[str, Any] | None = None,
) -> Any:
    """Insert rows into a known ClickHouse table.

    Caller is responsible for passing only allowlisted table/column names.
    """
    if not rows:
        return None
    kwargs: dict[str, Any] = {"column_names": list(column_names)}
    if database is not None:
        kwargs["database"] = database
    if column_type_names is not None:
        kwargs["column_type_names"] = list(column_type_names)
    if settings is not None:
        kwargs["settings"] = settings
    return get_client().insert(table, data=list(rows), **kwargs)


def check_clickhouse_connection() -> dict[str, Any]:
    """Connectivity self-check for health/debug endpoints."""
    try:
        version_row = query_one("SELECT version()")
        return {
            "ok": True,
            "database": "clickhouse",
            "version": str(version_row[0]) if version_row else None,
            "url": f"{os.getenv('CLICKHOUSE_HOST', '127.0.0.1')}:{_int_env('CLICKHOUSE_PORT', 28123)}/{os.getenv('CLICKHOUSE_DATABASE', 'cynexus')}",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("clickhouse health check failed: %s", exc)
        return {
            "ok": False,
            "database": "clickhouse",
            "error": str(exc).strip().splitlines()[0][:300],
        }


__all__ = [
    "check_clickhouse_connection",
    "close_client",
    "command",
    "get_client",
    "insert",
    "query",
    "query_one",
    "query_rows",
]
