"""create ai provider registry tables

Revision ID: s2t3u4v5w6x7
Revises: r1s2t3u4v5w6
Create Date: 2026-06-25
"""
from __future__ import annotations

from alembic import op


revision: str = "s2t3u4v5w6x7"
down_revision: str | None = "r1s2t3u4v5w6"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS app.ai_providers (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code VARCHAR(64) NOT NULL,
            name VARCHAR(128) NOT NULL,
            provider_type VARCHAR(64) NOT NULL DEFAULT 'minimax',
            base_url VARCHAR(255),
            default_model VARCHAR(128),
            api_key TEXT,
            api_key_env VARCHAR(128),
            group_id VARCHAR(128),
            group_id_env VARCHAR(128),
            is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            timeout_seconds INTEGER,
            extra JSONB NOT NULL DEFAULT '{}'::jsonb,
            remark TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            deleted_at TIMESTAMPTZ,
            CONSTRAINT uq_ai_providers_code UNIQUE (code)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ai_providers_enabled ON app.ai_providers(is_enabled) WHERE deleted_at IS NULL")

    op.execute("""
        CREATE TABLE IF NOT EXISTS app.ai_usage_bindings (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            capability VARCHAR(64) NOT NULL,
            label VARCHAR(128) NOT NULL,
            provider_id UUID,
            model_override VARCHAR(128),
            is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            params JSONB NOT NULL DEFAULT '{}'::jsonb,
            remark TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            deleted_at TIMESTAMPTZ,
            CONSTRAINT uq_ai_usage_bindings_capability UNIQUE (capability)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ai_usage_bindings_provider ON app.ai_usage_bindings(provider_id) WHERE deleted_at IS NULL")

    op.execute("""
        INSERT INTO app.ai_providers (
            code, name, provider_type, base_url, default_model, api_key_env,
            group_id_env, timeout_seconds, remark
        )
        VALUES (
            'minimax-default',
            'MiniMax default',
            'minimax',
            'https://api.minimaxi.com',
            'MiniMax-M2.5',
            'MINIMAX_API_KEY',
            'MINIMAX_GROUP_ID',
            120,
            'Seeded from existing environment variables.'
        )
        ON CONFLICT (code) DO NOTHING
    """)

    op.execute("""
        WITH provider AS (
            SELECT id FROM app.ai_providers WHERE code = 'minimax-default' LIMIT 1
        )
        INSERT INTO app.ai_usage_bindings (capability, label, provider_id, model_override)
        SELECT capability, label, provider.id, model_override
        FROM provider
        CROSS JOIN (
            VALUES
                ('text_polish', 'MP4 text polish', 'MiniMax-M2.5'),
                ('text_summary', 'MP4 summary', 'MiniMax-M2.5'),
                ('post_metadata', 'Markdown metadata', 'MiniMax-M2.5'),
                ('mp4_qa', 'MP4 Ask AI', 'MiniMax-M2.5'),
                ('application_analysis', 'Stock application analysis', 'MiniMax-M2.7'),
                ('application_recent30', 'Recent 30-day analysis', 'MiniMax-M2.7'),
                ('auction_analysis', 'Auction AI analysis', 'MiniMax-M2.7')
        ) AS seed(capability, label, model_override)
        ON CONFLICT (capability) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.ai_usage_bindings")
    op.execute("DROP TABLE IF EXISTS app.ai_providers")
