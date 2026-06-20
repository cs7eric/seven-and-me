"""Postgres 健康检查 service.

供 :mod:`backend.api.system` 在 ``/api/status`` 里挂接, 也可单独 ``GET /api/system/db-health``.
"""
from __future__ import annotations

from backend.config.database import check_database_connection


def check_db_health() -> dict:
    """透传 :func:`backend.config.database.check_database_connection` 的结果."""
    return check_database_connection()


__all__ = ["check_db_health"]
