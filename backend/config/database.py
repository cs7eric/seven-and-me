"""Postgres / SQLAlchemy engine + session 入口.

只放 engine / SessionLocal / 事务边界. 表结构定义在 :mod:`backend.models`,
CRUD 在 :mod:`backend.repositories`.

约定:
  - 不要在 API 层直接 ``create_engine``
  - 不要在 repository 里 commit (事务边界 = API 入口处的 ``session_scope``)
  - 一个请求一个 session, 离开 scope 自动 close

⚠️ 导入时机: ``backend.bootstrap`` / ``backend.api.self_selected`` 会在
``app_factory.create_app()`` 调 ``load_dotenv()`` **之前** import 到本模块.
所以 engine / SessionLocal / session_scope 必须**懒加载** — 真要用时再读 env,
不要在模块顶层 ``raise RuntimeError``. 第一次访问 ``engine`` 或 ``SessionLocal``
时如果 DATABASE_URL 仍未配置, 那时才报错.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 懒加载: 第一次访问 engine / SessionLocal / session_scope 时再读 DATABASE_URL
# ---------------------------------------------------------------------------

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not configured. "
            "Set it in .env (e.g. postgresql+psycopg://postgres:password@localhost:25432/postgres). "
            "Note: app_factory.create_app() calls load_dotenv() — make sure it runs before "
            "any code path that opens a DB session."
        )
    return url


def _build_engine() -> Engine:
    url = _get_database_url()
    echo = os.getenv("SQLALCHEMY_ECHO", "false").lower() == "true"
    return create_engine(
        url,
        echo=echo,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=1800,
        future=True,
    )


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def _get_sessionmaker() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=_get_engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )
    return _SessionLocal


# 兼容 import `from backend.config.database import engine, SessionLocal` 的旧写法:
# 用 __getattr__ (PEP 562) 让属性访问也走懒加载.

def __getattr__(name: str):
    if name == "engine":
        return _get_engine()
    if name == "SessionLocal":
        return _get_sessionmaker()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """事务边界: API 入口处 with session_scope() as db → 块结束 commit / rollback / close.

    用法::

        from backend.config.database import session_scope
        from backend.repositories.stock.self_selected_db_repo import SelfSelectedRepository

        with session_scope() as db:
            repo = SelfSelectedRepository(db)
            return jsonify(repo.list_groups())
    """
    SessionLocal = _get_sessionmaker()
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db_session() -> Session:
    """直接拿一个 Session, 自行管理 close (进阶用法, 一般场景请用 session_scope)."""
    return _get_sessionmaker()()


def check_database_connection() -> dict:
    """连通性自检: SELECT 1 + 版本号. 给 db_health_service 用."""
    url_for_log = "<unconfigured>"
    try:
        url = _get_database_url()
        url_for_log = url.split("@")[-1]
    except RuntimeError as exc:
        return {
            "ok": False,
            "database": "postgresql",
            "error": str(exc),
            "url": url_for_log,
        }
    try:
        with _get_engine().connect() as conn:
            version = conn.execute(text("select version()")).scalar_one()
        return {
            "ok": True,
            "database": "postgresql",
            "version": version,
            "url": url_for_log,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("database health check failed: %s", exc)
        return {
            "ok": False,
            "database": "postgresql",
            "error": str(exc).strip().splitlines()[0][:300],
            "url": url_for_log,
        }


__all__ = [
    "engine",
    "SessionLocal",
    "session_scope",
    "get_db_session",
    "check_database_connection",
]
