"""DuckDB connection + helpers for the market-data warehouse.

Single source of truth: F:/dev-repo/mp4-to-word-new/reference/stock/duckdb/market_data.duckdb
Schema: see reference/stock/duckdb/schema.sql

DuckDB 跨进程锁说明 (重要):
  DuckDB 是嵌入式数据库, 不是 client/server. 同一个 .duckdb 文件**不能**多进程同时
  以 read_write 模式打开 — 第二个进程会撞 OS-level 文件锁抛 _duckdb.IOException.

  老实现用 process-wide 单例 ``_conn`` + retry-with-backoff, 后果:
    - Flask / scheduler 进程一启动就常驻连接, 文件一直被这个进程锁住
    - 任何想开第二个 read_write 连接的进程 (e.g. daily_eod_incremental 脚本) 永远打不开
    - retry 多久都没用, 永久锁就是永久锁

  新实现改成**短连接** (按需 open, 用完 close):
    - ``with conn(read_only=False) as con: ...`` — 显式 scope, 块结束自动 close, 立刻释放文件锁
    - ``get_conn(read_only=False)`` — 兼容旧 API, 返回的连接在 GC (``__del__``) 时自动 close
      (CPython 引用计数立刻触发, 实际上等同于"函数返回就 close")
    - 多进程冲突场景变成**协作式**: Flask 只在处理 HTTP 时瞬间持锁, 中间空闲期
      daily 脚本就能拿到锁. 真要双方同时写, 任一方还是会撞锁, 这是 DuckDB 本身限制.

用法 (推荐):
    from backend.adapters.market.duckdb_store import conn, get_conn, init_schema

    # 写入 (read_write, 独占)
    with conn(read_only=False) as con:
        con.execute("INSERT INTO ... SELECT ...")

    # 只读 (可多个进程同时 read_only)
    with conn(read_only=True) as con:
        rows = con.execute("SELECT * FROM daily_raw").fetchall()

用法 (兼容旧 API, 不推荐新代码用):
    con = get_conn()              # 返回的连接 GC 时自动 close
    con.execute("...")

    # 旧风格的 "裸" 短连接 (跟 get_conn 等价, 但不包装 __del__):
    con = get_conn()
    try:
        con.execute("...")
    finally:
        con.close()
"""
from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import duckdb

logger = logging.getLogger(__name__)

# Repo root: F:\dev-repo\mp4-to-word-new
# __init__.py lives at backend/adapters/market/duckdb_store/__init__.py
# parents[0..3] = duckdb_store, market, adapters, backend -> parents[4] = repo root
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DB_PATH = _REPO_ROOT / "reference" / "stock" / "duckdb" / "market_data.duckdb"
_SCHEMA_PATH = _REPO_ROOT / "reference" / "stock" / "duckdb" / "schema.sql"
_LOCK_PATH = _DB_PATH.with_suffix(_DB_PATH.suffix + ".lock")

# 锁冲突重试配置: 跟 process-wide 单例时一样, 解决**短时**锁冲突
# (e.g. scheduler tick 1-2s 写完). 永久锁靠协作 (短连接) 解决, 不靠重试.
_MAX_LOCK_CONFLICT_RETRIES = 6
_LOCK_BACKOFFS = (0.5, 1.0, 2.0, 4.0, 4.0, 4.0)  # 累计 ≈ 15.5s
_PROCESS_LOCK = threading.RLock()
_TLS = threading.local()


def get_db_path() -> Path:
    return _DB_PATH


def get_schema_path() -> Path:
    return _SCHEMA_PATH


class _InterProcessDuckDBLock:
    """A small cross-process file lock held for the whole DuckDB connection lifetime."""

    def __init__(self) -> None:
        self._fh = None

    def acquire(self) -> None:
        _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        fh = open(_LOCK_PATH, "a+b")
        fh.seek(0, os.SEEK_END)
        if fh.tell() == 0:
            fh.write(b"0")
            fh.flush()
        fh.seek(0)
        if os.name == "nt":
            import msvcrt

            while True:
                try:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.2)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        self._fh = fh

    def release(self) -> None:
        fh = self._fh
        self._fh = None
        if fh is None:
            return
        try:
            fh.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


def _active_connection() -> duckdb.DuckDBPyConnection | None:
    return getattr(_TLS, "connection", None)


def _set_active_connection(con: duckdb.DuckDBPyConnection | None) -> None:
    if con is None:
        if hasattr(_TLS, "connection"):
            delattr(_TLS, "connection")
        return
    _TLS.connection = con


def _open_locked_connection(read_only: bool) -> tuple[duckdb.DuckDBPyConnection, _InterProcessDuckDBLock]:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PROCESS_LOCK.acquire()
    file_lock = _InterProcessDuckDBLock()
    try:
        file_lock.acquire()
        con = _connect_with_lock_retry(read_only=read_only)
        _set_active_connection(con)
        return con, file_lock
    except Exception:
        file_lock.release()
        _PROCESS_LOCK.release()
        raise


def _close_locked_connection(con: duckdb.DuckDBPyConnection, file_lock: _InterProcessDuckDBLock) -> None:
    try:
        try:
            con.close()
        except Exception:  # noqa: BLE001
            pass
    finally:
        _set_active_connection(None)
        file_lock.release()
        _PROCESS_LOCK.release()


# ---------------------------------------------------------------------------
# Lock-conflict 短时重试
# ---------------------------------------------------------------------------
# DuckDB OS-level 文件锁等待默认 ~5s 就抛. 包一层 retry, 让"scheduler 短持锁"
# 这类瞬态冲突不会硬失败. 注意这只解决**短时**冲突 — 永久锁永远 retry 也救不了,
# 靠"短连接 + 进程间协作"消化, 见文件顶部 docstring.

def _is_lock_conflict_msg(msg: str) -> bool:
    return (
        "另一个程序正在使用此文件" in msg
        or "File is already open" in msg
        or "Could not set lock" in msg
    )


def _connect_with_lock_retry(read_only: bool) -> duckdb.DuckDBPyConnection:
    """duckdb.connect() 包一层重试, 处理"另一进程刚 hold 锁 ~1-2s" 这种瞬态冲突."""
    last_exc: Exception | None = None
    for attempt in range(_MAX_LOCK_CONFLICT_RETRIES):
        try:
            return duckdb.connect(str(_DB_PATH), read_only=read_only)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            msg = str(exc)
            is_lock = _is_lock_conflict_msg(msg)
            if not is_lock or attempt == _MAX_LOCK_CONFLICT_RETRIES - 1:
                logger.warning(
                    "duckdb connect(read_only=%s) failed (attempt %d/%d): %s",
                    read_only, attempt + 1, _MAX_LOCK_CONFLICT_RETRIES, exc,
                )
                raise
            backoff = _LOCK_BACKOFFS[attempt]
            logger.info(
                "duckdb lock held by another process, retry in %.1fs (attempt %d/%d): %s",
                backoff, attempt + 1, _MAX_LOCK_CONFLICT_RETRIES, msg.strip().splitlines()[0][:200],
            )
            time.sleep(backoff)
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 公开 API: 短连接 (per-call)
# ---------------------------------------------------------------------------

@contextmanager
def conn(read_only: bool = False) -> Iterator[duckdb.DuckDBPyConnection]:
    """短连接 context manager — 强烈推荐.

    ```python
    with conn(read_only=False) as con:
        con.execute("INSERT INTO ...")
    ```
    块结束自动 close, 立刻释放 OS 文件锁, 让其他 Python 进程能拿到.

    DuckDB 不允许同进程同一文件开多个 read_write 连接, 但允许只读连接多个并存.
    跨进程 read_write 互斥 (DuckDB 嵌入式本质, 见文件顶部 docstring).
    """
    active = _active_connection()
    if active is not None:
        yield active
        return

    con, file_lock = _open_locked_connection(read_only=read_only)
    try:
        yield con
    finally:
        _close_locked_connection(con, file_lock)


class _AutoCloseConn:
    """包装 duckdb connection, 在 GC (__del__) 时自动 close, 兼容 ``con = get_conn(); con.execute(...)`` 风格.

    CPython 引用计数让 __del__ 在变量出 scope 时立刻触发, 实际行为 = "函数返回就 close".
    新代码请用 ``with conn() as con:`` 更显式.

    同时实现 __enter__/__exit__, 让它本身也能当 context manager (跟 ``conn()`` 等价).

    ⚠️ 不要用链式 ``get_conn().execute().fetchone()`` 模式:
        CPython 表达式求值时, 中间 result 对象会持有底层 conn 的反向引用. __del__
        触发顺序不保证, 可能 wrapper 早于 result 被回收, 关掉连接后 result 再用
        就会抛 ``Connection already closed``. 30+ caller 中只有 1 处 (limit_emotion_service
        的 _latest_trade_date) 用了链式, 已改成显式 try/finally close.
    """

    __slots__ = ("_con", "_closed", "_file_lock", "_borrowed")

    def __init__(
        self,
        con: duckdb.DuckDBPyConnection,
        file_lock: _InterProcessDuckDBLock | None = None,
        *,
        borrowed: bool = False,
    ):
        self._con = con
        self._closed = False
        self._file_lock = file_lock
        self._borrowed = borrowed

    def __enter__(self) -> duckdb.DuckDBPyConnection:
        if self._closed:
            raise RuntimeError("connection already closed")
        return self._con

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._borrowed:
            return
        if self._file_lock is None:
            try:
                self._con.close()
            except Exception:  # noqa: BLE001
                pass
            return
        _close_locked_connection(self._con, self._file_lock)

    def __getattr__(self, name: str) -> Any:
        # 大部分方法 (execute / executemany / fetchone / fetchall / commit) 走这里
        if name in ("_con", "_closed", "_file_lock", "_borrowed", "close", "__enter__", "__exit__"):
            raise AttributeError(name)
        return getattr(self._con, name)

    def __del__(self) -> None:
        # CPython 引用计数触发: 函数返回 / 出 scope 时 close
        self.close()


def get_conn(read_only: bool = False) -> _AutoCloseConn:
    """开一条**短连接**, 兼容旧 ``con = get_conn(); con.execute(...)`` 风格.

    返回的连接在 GC 时 (CPython 上 = 函数返回时) 自动 close, 释放文件锁.
    新代码推荐用 ``with conn(read_only=...) as con:`` 更显式.
    """
    active = _active_connection()
    if active is not None:
        return _AutoCloseConn(active, borrowed=True)

    con, file_lock = _open_locked_connection(read_only=read_only)
    return _AutoCloseConn(con, file_lock=file_lock)


# ---------------------------------------------------------------------------
# 便利函数: 一次性脚本
# ---------------------------------------------------------------------------

def init_schema() -> None:
    """Run schema.sql. Idempotent (CREATE TABLE IF NOT EXISTS)."""
    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    with conn() as con:
        con.execute(sql)


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
    with conn() as con:
        for t in targets:
            try:
                out[t] = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
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
