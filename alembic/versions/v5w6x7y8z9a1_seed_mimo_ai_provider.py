"""seed mimo-default ai provider

Revision ID: v5w6x7y8z9a1
Revises: u4v5w6x7y8z9
Create Date: 2026-06-26
"""
from __future__ import annotations

from alembic import op


revision: str = "v5w6x7y8z9a1"
down_revision: str | None = "u4v5w6x7y8z9"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO app.ai_providers (
            code, name, provider_type, base_url, default_model, api_key, models,
            timeout_seconds, remark
        )
        VALUES (
            'mimo-default',
            'MiMo v2.5 Pro',
            'anthropic_compatible',
            'https://api.xiaomimimo.com/anthropic',
            'mimo-v2.5-pro',
            'sk-cfukzo8cdbpfe2oficf5h2nixuxoiyx66ir7618gtpcv5231',
            '["mimo-v2.5-pro"]'::jsonb,
            120,
            'Xiaomi MiMo Anthropic-compatible endpoint.'
        )
        ON CONFLICT (code) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM app.ai_providers WHERE code = 'mimo-default'")
