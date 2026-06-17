"""DuckDB connection + helpers for the market-data warehouse.

Single source of truth: F:/dev-repo/mp4-to-word-new/reference/stock/duckdb/market_data.duckdb
Schema: see reference/stock/duckdb/schema.sql

Usage:
    from backend.adapters.market.duckdb_store import get_conn, init_schema
    init_schema()  # idempotent
    with get_conn() as con:
        con.execute("SELECT count(*) FROM daily_raw").fetchone()
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import duckdb

# Repo root: F:\dev-repo\mp4-to-word-new
# __init__.py lives at backend/adapters/market/duckdb_store/__init__.py
# parents[0..3] = duckdb_store, market, adapters, backend -> parents[4] = repo root
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DB_PATH = _REPO_ROOT / "reference" / "stock" / "duckdb" / "market_data.duckdb"
_SCHEMA_PATH = _REPO_ROOT / "reference" / "stock" / "duckdb" / "schema.sql"

# DuckDB is in-process; one connection per thread is the safe default.
_local = threading.local()


def get_db_path() -> Path:
    return _DB_PATH


def get_schema_path() -> Path:
    return _SCHEMA_PATH


def get_conn() -> duckdb.DuckDBPyConnection:
    """Return a thread-local DuckDB connection (read-write).

    Local single-file store: one connection per thread is sufficient. DuckDB
    does not allow mixing read-only and read-write connections on the same
    file, so we standardize on rw; readers simply don't write.
    """
    if not hasattr(_local, "conn"):
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = duckdb.connect(str(_DB_PATH))
    return _local.conn


@contextmanager
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    """Context manager wrapper around get_conn()."""
    c = get_conn()
    try:
        yield c
    except Exception:
        raise


def init_schema() -> None:
    """Run schema.sql. Idempotent (CREATE TABLE IF NOT EXISTS)."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    with conn() as c:
        c.execute(sql)


def table_stats() -> dict[str, int]:
    """Return row counts for the main tables. Useful for smoke tests."""
    targets = [
        "stock_universe",
        "daily_raw",
        "daily_qfq",
        "daily_hfq",
        "corp_events",
        "adj_factors",
        "intraday_bars",
        "quotes",
        "ingest_state",
        "index_daily_raw",
        "ma_count_daily",
        "index_returns_daily",
    ]
    out: dict[str, int] = {}
    with conn() as c:
        for t in targets:
            try:
                out[t] = c.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            except duckdb.CatalogException:
                out[t] = -1  # table not yet created
    return out


if __name__ == "__main__":
    # Smoke test: init schema and print table stats.
    init_schema()
    print(f"DuckDB file: {_DB_PATH}")
    print(f"Schema file: {_SCHEMA_PATH}")
    print("Table row counts:")
    for t, n in table_stats().items():
        print(f"  {t:20s} {n:>12d}")
