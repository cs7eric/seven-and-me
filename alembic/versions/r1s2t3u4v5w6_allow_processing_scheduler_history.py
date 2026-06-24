"""allow processing scheduler history status

Revision ID: r1s2t3u4v5w6
Revises: q0r1s2t3u4v5
Create Date: 2026-06-24
"""
from __future__ import annotations

from alembic import op

revision: str = "r1s2t3u4v5w6"
down_revision: str | None = "q0r1s2t3u4v5"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE app.scheduler_job_run_history
        DROP CONSTRAINT IF EXISTS ck_scheduler_job_run_history_status
    """)
    op.execute("""
        ALTER TABLE app.scheduler_job_run_history
        ADD CONSTRAINT ck_scheduler_job_run_history_status CHECK (
            status IN ('success', 'failed', 'skipped', 'running', 'processing')
        )
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE app.scheduler_job_run_history
           SET status = 'running'
         WHERE status = 'processing'
    """)
    op.execute("""
        ALTER TABLE app.scheduler_job_run_history
        DROP CONSTRAINT IF EXISTS ck_scheduler_job_run_history_status
    """)
    op.execute("""
        ALTER TABLE app.scheduler_job_run_history
        ADD CONSTRAINT ck_scheduler_job_run_history_status CHECK (
            status IN ('success', 'failed', 'skipped', 'running')
        )
    """)
