"""Scheduler DB 仓库 (Postgres).

替代 :mod:`backend.api.scheduler` 里所有 ``scheduler/jobs.json`` + 内嵌 Python dict 的数据源.
"""
from backend.repositories.scheduler.job_repo import SchedulerJobRepository

__all__ = ["SchedulerJobRepository"]