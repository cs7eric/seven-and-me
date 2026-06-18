"""DuckDB connection + helpers for the market-data warehouse.

Single source of truth: F:/dev-repo/mp4-to-word-new/reference/stock/duckdb/market_data.duckdb
Schema: see reference/stock/duckdb/schema.sql

Usage:
    from backend.adapters.market.duckdb_store import get_conn, init_schema
    init_schema()  # idempotent
    con = get_conn()
    con.execute("SELECT count(*) FROM daily_raw").fetchone()

Connection model:
  - 单 process-wide connection (DuckDB 不允许同进程对同一 .duckdb 文件开多个连接 —
    OS-level 文件锁冲突).
  - get_conn() 返回一个 _LockedConnection 包装对象, 每次 .execute() / .executemany()
    自动获取 process-wide 锁, 兼容旧代码 (原 `con = get_conn(); con.execute(...)` 风格).
  - 多请求线程安全 (Flask `threaded=True` 下 Werkzeug 每个请求一个新线程).

  - 也提供 `conn()` context manager (高级用法): 同一块内多次 query 共用 1 把锁.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import duckdb

# Repo root: F:\dev-repo\mp4-to-word-new
# __init__.py lives at backend/adapters/market/duckdb_store/__init__.py
# parents[0..3] = duckdb_store, market, adapters, backend -> parents[4] = repo root
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DB_PATH = _REPO_ROOT / "reference" / "stock" / "duckdb" / "market_data.duckdb"
_SCHEMA_PATH = _REPO_ROOT / "reference" / "stock" / "duckdb" / "schema.sql"

# 单 connection per process + 单 lock 保护. 替代原来的 thread-local
# (threaded Flask 会让每个请求线程都试图开连接 → duckdb 文件锁冲突).
_conn: duckdb.DuckDBPyConnection | None = None
_conn_lock = threading.Lock()
_conn_init_lock = threading.Lock()


def get_db_path() -> Path:
    return _DB_PATH


def get_schema_path() -> Path:
    return _SCHEMA_PATH


def _ensure_conn() -> duckdb.DuckDBPyConnection:
    """Lazy-init process-wide connection (双锁, 防止 init 竞态)."""
    global _conn
    if _conn is not None:
        return _conn
    with _conn_init_lock:
        if _conn is None:
            _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            _conn = duckdb.connect(str(_DB_PATH))
    return _conn


class _LockedConnection:
    """Thread-safe wrapper around a process-wide DuckDB connection.

    Each .execute() / .executemany() acquires the process-wide lock for its
    duration. For short queries this is cheap (~µs); long operations (bulk
    inserts spanning multiple execute calls) should use `conn()` context
    manager instead to hold the lock once for the entire block.
    """

    __slots__ = ("_inner",)

    def __init__(self, inner: duckdb.DuckDBPyConnection):
        self._inner = inner

    def execute(self, sql: str, params: Any = None):
        with _conn_lock:
            if params is None:
                return self._inner.execute(sql)
            return self._inner.execute(sql, params)

    def executemany(self, sql: str, params: Any = None):
        with _conn_lock:
            if params is None:
                return self._inner.executemany(sql)
            return self._inner.executemany(sql, params)

    def __getattr__(self, name: str):
        # 委托其它方法 (commit, rollback, close, fetchone, fetchall...) 给底层连接,
        # 但调用时自动包一层锁.
        attr = getattr(self._inner, name)

        def locked_call(*args, **kwargs):
            with _conn_lock:
                return attr(*args, **kwargs)

        return locked_call


@contextmanager
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    """Process-wide DuckDB connection (BARE, 取锁请用 get_conn()).

    高级用法: 同一块多次 query 共用 1 把锁 (比每次 query 单独取锁快).
    """
    c = _ensure_conn()
    yield c


def init_schema() -> None:
    """Run schema.sql. Idempotent (CREATE TABLE IF NOT EXISTS)."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    with _conn_lock:
        c = _ensure_conn()
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
    with _conn_lock:
        c = _ensure_conn()
        for t in targets:
            try:
                out[t] = c.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            except duckdb.CatalogException:
                out[t] = -1  # table not yet created
    return out


# 兼容旧 API: get_conn() 返回 _LockedConnection, 每次 .execute() 自动取锁.
def get_conn() -> _LockedConnection:
    """返回 process-wide connection 的线程安全包装. 调用方无需手动加锁.

    Example:
        con = get_conn()
        rows = con.execute("SELECT * FROM ma_count_daily").fetchall()
    """
    return _LockedConnection(_ensure_conn())


if __name__ == "__main__":
    # Smoke test: init schema and print table stats.
    init_schema()
    print(f"DuckDB file: {_DB_PATH}")
    print(f"Schema file: {_SCHEMA_PATH}")
    print("Table row counts:")
    for t, n in table_stats().items():
        print(f"  {t:20s} {n:>12d}")
