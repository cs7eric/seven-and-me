"""Alembic env — 从 .env 读 DATABASE_URL, target_metadata = Base.metadata.

约定:
  - 不要再把 DATABASE_URL 写进 alembic.ini, 走 env 变量
  - 所有新 ORM model 必须 ``import backend.models`` 才会被 autogenerate 识别
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

from alembic import context

# 让 backend.* 可被 import
import sys
from pathlib import Path
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.db.base import Base  # noqa: E402
import backend.models  # noqa: F401, E402  # 触发 model 注册到 Base.metadata

# 加载 .env (load_dotenv 是 idempotent)
load_dotenv()

config = context.config

if config.config_file_name is not None:
    # Windows GBK 默认编码读 alembic.ini 的中文注释会炸, 强制 UTF-8
    import io
    with open(config.config_file_name, encoding="utf-8") as _f:
        _ini_text = _f.read()
    fileConfig(io.StringIO(_ini_text))

database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL is not configured (env.py)")
config.set_main_option("sqlalchemy.url", database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """offline 模式: 只 emit SQL, 不真连 DB."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """online 模式: 真连 DB 跑迁移."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,  # 列类型变化也能 detect
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
