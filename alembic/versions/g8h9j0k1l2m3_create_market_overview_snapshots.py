"""create market overview snapshots table

Revision ID: g8h9j0k1l2m3
Revises: f1c3a7b9d2e4
Create Date: 2026-06-23 20:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "g8h9j0k1l2m3"
down_revision: Union[str, Sequence[str], None] = "f1c3a7b9d2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ensure extensions and schema exist
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
        "market_overview_snapshots",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("trade_date", sa.Date(), nullable=False),

        # 大盘成交额
        sa.Column("total_amount", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("total_volume", sa.Numeric(precision=18, scale=4), nullable=True),

        # 涨跌家数
        sa.Column("rising_count", sa.Integer(), nullable=True),
        sa.Column("falling_count", sa.Integer(), nullable=True),
        sa.Column("flat_count", sa.Integer(), nullable=True),
        sa.Column("limit_up_count", sa.Integer(), nullable=True),
        sa.Column("limit_down_count", sa.Integer(), nullable=True),
        sa.Column("stock_count", sa.Integer(), nullable=True),

        # 资金流 — 净流入 (亿)
        sa.Column("main_net_inflow", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("super_large_net_inflow", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("large_net_inflow", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("medium_net_inflow", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("small_net_inflow", sa.Numeric(precision=18, scale=4), nullable=True),

        # 资金流 — 净比 (%)
        sa.Column("main_net_inflow_ratio", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("super_large_net_ratio", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("large_net_ratio", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("medium_net_ratio", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("small_net_ratio", sa.Numeric(precision=6, scale=2), nullable=True),

        # 元数据
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("is_manual_override", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("manual_updated_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),

        sa.PrimaryKeyConstraint("id"),
        schema="app",
    )

    op.execute(
        """
        CREATE UNIQUE INDEX uk_market_overview_snapshots_trade_date_alive
        ON app.market_overview_snapshots (trade_date)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_market_overview_snapshots_trade_date_desc
        ON app.market_overview_snapshots (trade_date DESC)
        WHERE deleted_at IS NULL
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_market_overview_snapshots_updated_at
        BEFORE UPDATE ON app.market_overview_snapshots
        FOR EACH ROW
        EXECUTE FUNCTION app.set_updated_at()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_market_overview_snapshots_updated_at ON app.market_overview_snapshots")
    op.execute("DROP INDEX IF EXISTS app.uk_market_overview_snapshots_trade_date_alive")
    op.execute("DROP INDEX IF EXISTS app.idx_market_overview_snapshots_trade_date_desc")
    op.drop_table("market_overview_snapshots", schema="app")
