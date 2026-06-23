"""create market_limit_daily_stocks

Revision ID: q0r1s2t3u4v5
Revises: l4m5n6o7p8q9
Create Date: 2026-06-23

维护前请先看:
`F:\dev-repo\mp4-to-word-new\design\backend\limit-emotion-json-to-postgres.md`
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "q0r1s2t3u4v5"
down_revision: str | None = "l4m5n6o7p8q9"
branch_labels: None = None
depends_on: None = None

TABLE = "market_limit_daily_stocks"
SCHEMA = "app"
FK_TABLE = f"{SCHEMA}.{TABLE}"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("trade_date", sa.Date, nullable=False),

        # 股票信息
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("name", sa.String(64), nullable=True),

        # 分类: limit_up / limit_down / broken
        sa.Column("category", sa.String(16), nullable=False),

        # 板数 (limit_up: 当前连板数; broken: 前一日连板数; limit_down: 0)
        sa.Column("streak", sa.Integer, nullable=True),

        # 价格/涨跌幅
        sa.Column("change_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("limit_up_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("limit_down_price", sa.Numeric(12, 4), nullable=True),

        # 标准时间戳
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),

        schema=SCHEMA,
    )

    op.execute(f"""
        CREATE UNIQUE INDEX uk_{TABLE}_trade_date_code
        ON {FK_TABLE} (trade_date, code)
        WHERE deleted_at IS NULL
    """)
    op.execute(f"""
        CREATE INDEX idx_{TABLE}_trade_date_category
        ON {FK_TABLE} (trade_date DESC, category)
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
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.uk_{TABLE}_trade_date_code")
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.idx_{TABLE}_trade_date_category")
    op.drop_table(TABLE, schema=SCHEMA)
