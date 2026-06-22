"""create application analysis target tables

Revision ID: e2a6c1d4f8b3
Revises: d7e9b5f4a1c2
Create Date: 2026-06-22 00:20:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "e2a6c1d4f8b3"
down_revision: Union[str, Sequence[str], None] = "d7e9b5f4a1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.set_updated_at()
        RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.create_table(
        "application_analysis_configs",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("config_key", sa.String(length=64), nullable=False, server_default="default"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("horizon_days", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("horizon_segments", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("monthly_keep", sa.Integer(), nullable=False, server_default="6"),
        sa.Column("weekly_keep", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_application_analysis_configs_status"),
        sa.PrimaryKeyConstraint("id"),
        schema="app",
    )

    op.create_table(
        "application_analysis_targets",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("target_key", sa.String(length=64), nullable=False),
        sa.Column("legacy_key", sa.String(length=64), nullable=True),
        sa.Column("self_selected_item_id", sa.UUID(), nullable=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("market", sa.String(length=8), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False, server_default="stock"),
        sa.Column("adjust", sa.String(length=16), nullable=False, server_default="qfq"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_application_analysis_targets_status"),
        sa.CheckConstraint(
            "target_type IN ('stock', 'hk_stock', 'etf', 'index', 'other')",
            name="ck_application_analysis_targets_target_type",
        ),
        sa.CheckConstraint(
            "source_type IN ('manual', 'search', 'imported', 'self_selected_sync')",
            name="ck_application_analysis_targets_source_type",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="app",
    )

    op.execute(
        """
        CREATE UNIQUE INDEX uk_application_analysis_configs_key_alive
        ON app.application_analysis_configs (config_key)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uk_application_analysis_targets_target_key_alive
        ON app.application_analysis_targets (target_key)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uk_application_analysis_targets_legacy_key_alive
        ON app.application_analysis_targets (legacy_key)
        WHERE legacy_key IS NOT NULL AND deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_application_analysis_targets_self_selected_item_id
        ON app.application_analysis_targets (self_selected_item_id)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_application_analysis_targets_status_sort_order
        ON app.application_analysis_targets (status, sort_order, created_at DESC)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_application_analysis_targets_symbol
        ON app.application_analysis_targets (symbol, created_at DESC)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_application_analysis_configs_updated_at
        BEFORE UPDATE ON app.application_analysis_configs
        FOR EACH ROW
        EXECUTE FUNCTION app.set_updated_at()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_application_analysis_targets_updated_at
        BEFORE UPDATE ON app.application_analysis_targets
        FOR EACH ROW
        EXECUTE FUNCTION app.set_updated_at()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_application_analysis_targets_updated_at ON app.application_analysis_targets")
    op.execute("DROP TRIGGER IF EXISTS trg_application_analysis_configs_updated_at ON app.application_analysis_configs")
    op.drop_table("application_analysis_targets", schema="app")
    op.drop_table("application_analysis_configs", schema="app")
