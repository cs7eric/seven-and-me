"""add models column to ai_providers

Revision ID: u4v5w6x7y8z9
Revises: t3u4v5w6x7y8
Create Date: 2026-06-25
"""
from __future__ import annotations

from alembic import op


revision: str = "u4v5w6x7y8z9"
down_revision: str | None = "t3u4v5w6x7y8"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE app.ai_providers
        ADD COLUMN IF NOT EXISTS models JSONB NOT NULL DEFAULT '[]'::jsonb
    """)
    # Seed existing providers: put default_model into models array
    op.execute("""
        UPDATE app.ai_providers
        SET models = jsonb_build_array(default_model)
        WHERE default_model IS NOT NULL
          AND default_model <> ''
          AND (models IS NULL OR models = '[]'::jsonb)
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE app.ai_providers DROP COLUMN IF EXISTS models")
