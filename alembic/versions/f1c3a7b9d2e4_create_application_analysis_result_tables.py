"""create application analysis result tables

Revision ID: f1c3a7b9d2e4
Revises: e2a6c1d4f8b3
Create Date: 2026-06-21 23:40:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "f1c3a7b9d2e4"
down_revision: Union[str, Sequence[str], None] = "e2a6c1d4f8b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "application_analysis_result_current",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("target_id", sa.UUID(), nullable=True),
        sa.Column("target_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="success"),
        sa.Column("analysis_run_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('success', 'failed')", name="ck_application_analysis_result_current_status"),
        sa.PrimaryKeyConstraint("id"),
        schema="app",
    )

    op.create_table(
        "application_analysis_result_history",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("target_id", sa.UUID(), nullable=True),
        sa.Column("target_key", sa.String(length=64), nullable=False),
        sa.Column("history_key", sa.String(length=128), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=True),
        sa.Column("analysis_run_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema="app",
    )

    op.create_table(
        "application_analysis_daily_snapshots",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("target_id", sa.UUID(), nullable=True),
        sa.Column("target_key", sa.String(length=64), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("snapshot_kind", sa.String(length=32), nullable=False, server_default="recent30"),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "snapshot_kind IN ('recent30')",
            name="ck_application_analysis_daily_snapshots_snapshot_kind",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="app",
    )

    op.execute(
        """
        CREATE UNIQUE INDEX uk_application_analysis_result_current_target_key_alive
        ON app.application_analysis_result_current (target_key)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uk_application_analysis_result_history_target_key_history_key_alive
        ON app.application_analysis_result_history (target_key, history_key)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uk_application_analysis_daily_snapshots_target_trade_kind_alive
        ON app.application_analysis_daily_snapshots (target_key, trade_date, snapshot_kind)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_application_analysis_result_history_target_run_at
        ON app.application_analysis_result_history (target_key, analysis_run_at DESC)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_application_analysis_daily_snapshots_target_trade_date
        ON app.application_analysis_daily_snapshots (target_key, trade_date DESC)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_application_analysis_result_current_updated_at
        BEFORE UPDATE ON app.application_analysis_result_current
        FOR EACH ROW
        EXECUTE FUNCTION app.set_updated_at()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_application_analysis_result_history_updated_at
        BEFORE UPDATE ON app.application_analysis_result_history
        FOR EACH ROW
        EXECUTE FUNCTION app.set_updated_at()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_application_analysis_daily_snapshots_updated_at
        BEFORE UPDATE ON app.application_analysis_daily_snapshots
        FOR EACH ROW
        EXECUTE FUNCTION app.set_updated_at()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_application_analysis_daily_snapshots_updated_at ON app.application_analysis_daily_snapshots")
    op.execute("DROP TRIGGER IF EXISTS trg_application_analysis_result_history_updated_at ON app.application_analysis_result_history")
    op.execute("DROP TRIGGER IF EXISTS trg_application_analysis_result_current_updated_at ON app.application_analysis_result_current")
    op.drop_table("application_analysis_daily_snapshots", schema="app")
    op.drop_table("application_analysis_result_history", schema="app")
    op.drop_table("application_analysis_result_current", schema="app")
