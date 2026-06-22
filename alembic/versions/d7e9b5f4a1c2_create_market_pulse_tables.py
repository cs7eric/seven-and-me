"""create market pulse tables

Revision ID: d7e9b5f4a1c2
Revises: c4b2f6a8d9e1
Create Date: 2026-06-21 23:10:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "d7e9b5f4a1c2"
down_revision: Union[str, Sequence[str], None] = "c4b2f6a8d9e1"
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
        "market_pulse_capture_batches",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False, server_default="live_capture"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="success"),
        sa.Column("source_name", sa.String(length=128), nullable=False, server_default="akshare.stock_fund_flow_industry"),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "source_kind IN ('live_capture', 'duckdb_import', 'json_import')",
            name="ck_market_pulse_capture_batches_source_kind",
        ),
        sa.CheckConstraint(
            "status IN ('success', 'partial', 'failed')",
            name="ck_market_pulse_capture_batches_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="app",
    )

    op.create_table(
        "market_pulse_sector_daily_snapshots",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("sector_name", sa.String(length=128), nullable=False),
        sa.Column("sector_index", sa.String(length=64), nullable=True),
        sa.Column("rank_by_change", sa.Integer(), nullable=True),
        sa.Column("change_pct", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("inflow", sa.Numeric(precision=24, scale=6), nullable=True),
        sa.Column("outflow", sa.Numeric(precision=24, scale=6), nullable=True),
        sa.Column("main_net", sa.Numeric(precision=24, scale=6), nullable=True),
        sa.Column("stock_count", sa.Integer(), nullable=True),
        sa.Column("leading_stock", sa.String(length=128), nullable=True),
        sa.Column("leading_change_pct", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("leading_price", sa.Numeric(precision=24, scale=6), nullable=True),
        sa.Column("source_kind", sa.String(length=32), nullable=False, server_default="live_capture"),
        sa.Column("source_name", sa.String(length=128), nullable=False, server_default="akshare.stock_fund_flow_industry"),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "source_kind IN ('live_capture', 'duckdb_import', 'json_import')",
            name="ck_market_pulse_sector_daily_snapshots_source_kind",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="app",
    )

    op.execute(
        """
        CREATE UNIQUE INDEX uk_market_pulse_capture_batches_trade_date_alive
        ON app.market_pulse_capture_batches (trade_date)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_market_pulse_capture_batches_fetched_at
        ON app.market_pulse_capture_batches (fetched_at DESC)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uk_market_pulse_sector_daily_snapshots_trade_date_sector_alive
        ON app.market_pulse_sector_daily_snapshots (trade_date, sector_name)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_market_pulse_sector_daily_snapshots_trade_date_rank
        ON app.market_pulse_sector_daily_snapshots (trade_date, rank_by_change ASC)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_market_pulse_sector_daily_snapshots_trade_date_main_net
        ON app.market_pulse_sector_daily_snapshots (trade_date, main_net DESC)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_market_pulse_sector_daily_snapshots_sector_trade_date
        ON app.market_pulse_sector_daily_snapshots (sector_name, trade_date DESC)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_market_pulse_sector_daily_snapshots_batch_id
        ON app.market_pulse_sector_daily_snapshots (batch_id)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_market_pulse_capture_batches_updated_at
        BEFORE UPDATE ON app.market_pulse_capture_batches
        FOR EACH ROW
        EXECUTE FUNCTION app.set_updated_at()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_market_pulse_sector_daily_snapshots_updated_at
        BEFORE UPDATE ON app.market_pulse_sector_daily_snapshots
        FOR EACH ROW
        EXECUTE FUNCTION app.set_updated_at()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_market_pulse_sector_daily_snapshots_updated_at ON app.market_pulse_sector_daily_snapshots")
    op.execute("DROP TRIGGER IF EXISTS trg_market_pulse_capture_batches_updated_at ON app.market_pulse_capture_batches")
    op.drop_table("market_pulse_sector_daily_snapshots", schema="app")
    op.drop_table("market_pulse_capture_batches", schema="app")
