"""SQLAlchemy declarative base.

所有 ORM model 必须继承 :class:`Base` 才能被 Alembic autogenerate 识别。
"""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
