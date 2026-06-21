"""create business self selected tables

Revision ID: b8f8c0f4c3d1
Revises: a3a7585b121c
Create Date: 2026-06-21 20:45:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b8f8c0f4c3d1"
down_revision: Union[str, Sequence[str], None] = "a3a7585b121c"
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
        "self_selected_lists",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("legacy_key", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("color", sa.String(length=32), nullable=False, server_default="blue"),
        sa.Column("list_kind", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_self_selected_lists_status"),
        sa.CheckConstraint("list_kind IN ('manual', 'system')", name="ck_self_selected_lists_list_kind"),
        sa.PrimaryKeyConstraint("id"),
        schema="app",
    )
    op.create_table(
        "self_selected_list_items",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("legacy_key", sa.String(length=64), nullable=True),
        sa.Column("list_id", sa.UUID(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("market", sa.String(length=8), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("target_type", sa.String(length=32), nullable=False, server_default="stock"),
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_self_selected_list_items_status"),
        sa.CheckConstraint(
            "target_type IN ('stock', 'hk_stock', 'etf', 'index', 'other')",
            name="ck_self_selected_list_items_target_type",
        ),
        sa.CheckConstraint(
            "source_type IN ('manual', 'search', 'imported')",
            name="ck_self_selected_list_items_source_type",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="app",
    )

    op.execute(
        """
        CREATE UNIQUE INDEX uk_self_selected_lists_legacy_key_alive
        ON app.self_selected_lists (legacy_key)
        WHERE legacy_key IS NOT NULL AND deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_self_selected_lists_status_sort_order
        ON app.self_selected_lists (status, sort_order, created_at DESC)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uk_self_selected_list_items_legacy_key_alive
        ON app.self_selected_list_items (legacy_key)
        WHERE legacy_key IS NOT NULL AND deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uk_self_selected_list_items_list_symbol_alive
        ON app.self_selected_list_items (list_id, symbol)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_self_selected_list_items_list_id_sort_order
        ON app.self_selected_list_items (list_id, sort_order, created_at DESC)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_self_selected_list_items_symbol
        ON app.self_selected_list_items (symbol, created_at DESC)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_self_selected_lists_updated_at
        BEFORE UPDATE ON app.self_selected_lists
        FOR EACH ROW
        EXECUTE FUNCTION app.set_updated_at()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_self_selected_list_items_updated_at
        BEFORE UPDATE ON app.self_selected_list_items
        FOR EACH ROW
        EXECUTE FUNCTION app.set_updated_at()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_self_selected_list_items_updated_at ON app.self_selected_list_items")
    op.execute("DROP TRIGGER IF EXISTS trg_self_selected_lists_updated_at ON app.self_selected_lists")
    op.drop_table("self_selected_list_items", schema="app")
    op.drop_table("self_selected_lists", schema="app")
