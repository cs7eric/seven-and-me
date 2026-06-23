"""create market_limit_daily_snapshots

Revision ID: l4m5n6o7p8q9
Revises: g8h9j0k1l2m3
Create Date: 2026-06-23

维护前请先看:
`F:\dev-repo\mp4-to-word-new\design\backend\limit-emotion-json-to-postgres.md`
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "l4m5n6o7p8q9"
down_revision: str | None = "g8h9j0k1l2m3"
branch_labels: None = None
depends_on: None = None

TABLE = "market_limit_daily_snapshots"
SCHEMA = "app"
FK_TABLE = f"{SCHEMA}.{TABLE}"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("trade_date", sa.Date, nullable=False),

        # 涨跌停 (limit up/down)
        sa.Column("limit_up_count", sa.Integer, nullable=True),
        sa.Column("limit_down_count", sa.Integer, nullable=True),

        # 触板/炸板
        sa.Column("touched_count", sa.Integer, nullable=True),
        sa.Column("broken_count", sa.Integer, nullable=True),
        sa.Column("break_board_rate", sa.Numeric(6, 4), nullable=True),

        # 连板
        sa.Column("max_streak_height", sa.Integer, nullable=True),
        sa.Column("promotion_overall_rate", sa.Numeric(6, 4), nullable=True),

        # 连板情绪
        sa.Column("sentiment_level", sa.String(32), nullable=True),
        sa.Column("sentiment_text", sa.Text, nullable=True),

        # 元数据
        sa.Column("stock_count", sa.Integer, nullable=True),
        sa.Column("market_status", sa.String(32), nullable=True),
        sa.Column("data_status", sa.String(32), nullable=True),
        sa.Column("source", sa.String(64), nullable=True),

        # 扩展字段 (full computed payload)
        sa.Column("extra", sa.dialects.postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),

        # 标准时间戳
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),

        schema=SCHEMA,
    )

    op.execute(f"""
        CREATE UNIQUE INDEX uk_{TABLE}_trade_date
        ON {FK_TABLE} (trade_date)
        WHERE deleted_at IS NULL
    """)
    op.execute(f"""
        CREATE INDEX idx_{TABLE}_trade_date_desc
        ON {FK_TABLE} (trade_date DESC)
        WHERE deleted_at IS NULL
    """)

    op.execute(f"""
        CREATE TRIGGER trg_{TABLE}_updated_at
        BEFORE UPDATE ON {FK_TABLE}
        FOR EACH ROW
        EXECUTE FUNCTION app.set_updated_at();
    """)


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_updated_at ON {FK_TABLE}")
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.uk_{TABLE}_trade_date")
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.idx_{TABLE}_trade_date_desc")
    op.drop_table(TABLE, schema=SCHEMA)
