"""create sector fund flow tables

Revision ID: c4b2f6a8d9e1
Revises: b8f8c0f4c3d1
Create Date: 2026-06-21 21:30:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c4b2f6a8d9e1"
down_revision: Union[str, Sequence[str], None] = "b8f8c0f4c3d1"
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
        "sector_fund_flow_capture_batches",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("scope", sa.String(length=32), nullable=False, server_default="industry"),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default="crawler"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="success"),
        sa.Column("source", sa.String(length=128), nullable=False, server_default="ths.10jqka.com.cn"),
        sa.Column("total_pages", sa.Integer(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("page_row_counts", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("scope IN ('industry', 'concept')", name="ck_sector_fund_flow_capture_batches_scope"),
        sa.CheckConstraint("source_type IN ('crawler', 'json_import')", name="ck_sector_fund_flow_capture_batches_source_type"),
        sa.CheckConstraint("status IN ('success', 'partial', 'failed')", name="ck_sector_fund_flow_capture_batches_status"),
        sa.PrimaryKeyConstraint("id"),
        schema="app",
    )
    op.create_table(
        "sector_fund_flow_daily_snapshots",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False, server_default="industry"),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("sector_code", sa.String(length=64), nullable=True),
        sa.Column("sector_name", sa.String(length=128), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("change_pct", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("inflow", sa.Numeric(precision=24, scale=6), nullable=True),
        sa.Column("outflow", sa.Numeric(precision=24, scale=6), nullable=True),
        sa.Column("net", sa.Numeric(precision=24, scale=6), nullable=True),
        sa.Column("company_count", sa.Integer(), nullable=True),
        sa.Column("leader_stock", sa.String(length=128), nullable=True),
        sa.Column("leader_change", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("leader_price", sa.Numeric(precision=24, scale=6), nullable=True),
        sa.Column("source", sa.String(length=128), nullable=False, server_default="ths.10jqka.com.cn"),
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default="crawler"),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("scope IN ('industry', 'concept')", name="ck_sector_fund_flow_daily_snapshots_scope"),
        sa.CheckConstraint("source_type IN ('crawler', 'json_import')", name="ck_sector_fund_flow_daily_snapshots_source_type"),
        sa.PrimaryKeyConstraint("id"),
        schema="app",
    )

    op.execute(
        """
        CREATE UNIQUE INDEX uk_sector_fund_flow_capture_batches_scope_trade_date_alive
        ON app.sector_fund_flow_capture_batches (scope, trade_date)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_sector_fund_flow_capture_batches_scope_fetched_at
        ON app.sector_fund_flow_capture_batches (scope, fetched_at DESC)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_sector_fund_flow_capture_batches_status_created_at
        ON app.sector_fund_flow_capture_batches (status, created_at DESC)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uk_sector_fund_flow_daily_snapshots_scope_trade_date_sector_alive
        ON app.sector_fund_flow_daily_snapshots (scope, trade_date, sector_name)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_sector_fund_flow_daily_snapshots_scope_trade_date_net
        ON app.sector_fund_flow_daily_snapshots (scope, trade_date, net DESC, rank ASC)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_sector_fund_flow_daily_snapshots_scope_sector_trade_date
        ON app.sector_fund_flow_daily_snapshots (scope, sector_name, trade_date DESC)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_sector_fund_flow_daily_snapshots_batch_id
        ON app.sector_fund_flow_daily_snapshots (batch_id)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_sector_fund_flow_capture_batches_updated_at
        BEFORE UPDATE ON app.sector_fund_flow_capture_batches
        FOR EACH ROW
        EXECUTE FUNCTION app.set_updated_at()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_sector_fund_flow_daily_snapshots_updated_at
        BEFORE UPDATE ON app.sector_fund_flow_daily_snapshots
        FOR EACH ROW
        EXECUTE FUNCTION app.set_updated_at()
        """
    )
    op.execute(
        """
        COMMENT ON TABLE app.sector_fund_flow_capture_batches IS
        'One active capture batch per scope and trade_date; overwritten batches are soft-deleted';
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN app.sector_fund_flow_capture_batches.extra IS
        'Crawler metadata and raw payload summary kept for troubleshooting';
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN app.sector_fund_flow_daily_snapshots.extra IS
        'Per-row raw source fields kept for import compatibility and future parsing fixes';
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_sector_fund_flow_daily_snapshots_updated_at ON app.sector_fund_flow_daily_snapshots")
    op.execute("DROP TRIGGER IF EXISTS trg_sector_fund_flow_capture_batches_updated_at ON app.sector_fund_flow_capture_batches")
    op.drop_table("sector_fund_flow_daily_snapshots", schema="app")
    op.drop_table("sector_fund_flow_capture_batches", schema="app")
