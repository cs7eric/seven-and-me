"""seed deepseek ai provider

Revision ID: t3u4v5w6x7y8
Revises: s2t3u4v5w6x7
Create Date: 2026-06-25
"""
from __future__ import annotations

from alembic import op


revision: str = "t3u4v5w6x7y8"
down_revision: str | None = "s2t3u4v5w6x7"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO app.ai_providers (
            code, name, provider_type, base_url, default_model, api_key_env,
            timeout_seconds, remark
        )
        VALUES (
            'deepseek-default',
            'DeepSeek default',
            'deepseek',
            'https://api.deepseek.com',
            'deepseek-v4-flash',
            'DEEPSEEK_API_KEY',
            120,
            'Seeded DeepSeek OpenAI-compatible provider. Bind capabilities in Settings > AI Provider.'
        )
        ON CONFLICT (code) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM app.ai_providers WHERE code = 'deepseek-default'")
