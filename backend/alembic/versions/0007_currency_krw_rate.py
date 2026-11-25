"""money in won; display in KRW or USD at an exchange rate (agent-room replies 33-35)

All stored money stays as it is (won). `currency` becomes the DISPLAY currency, KRW by default; USD amounts are
shown and entered at settings.usd_krw_rate, fetched automatically (rate_mode 'auto') or typed in ('manual').
Receipts entered in dollars keep the rate they were converted at (stock_documents.price_rate).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("settings", "currency", server_default="KRW")
    op.alter_column("settings", "currency_decimals", server_default="0")
    op.execute("UPDATE settings SET currency = 'KRW', currency_decimals = 0")
    op.add_column("settings", sa.Column("usd_krw_rate", sa.Numeric(12, 4)))
    op.add_column("settings", sa.Column("rate_mode", sa.String(8), nullable=False, server_default="auto"))
    op.add_column("settings", sa.Column("rate_source", sa.String(64)))
    op.add_column("settings", sa.Column("rate_date", sa.String(10)))  # the source's own date of the rate
    op.add_column("settings", sa.Column("rate_updated_at", sa.DateTime(timezone=True)))
    op.add_column("settings", sa.Column("rate_checked_at", sa.DateTime(timezone=True)))
    op.add_column("settings", sa.Column("rate_error", sa.String(200)))
    op.create_check_constraint("ck_settings_currency", "settings", "currency IN ('KRW', 'USD')")
    op.create_check_constraint("ck_settings_rate_mode", "settings", "rate_mode IN ('auto', 'manual')")
    op.create_check_constraint("ck_settings_rate", "settings", "usd_krw_rate IS NULL OR usd_krw_rate > 0")
    # DDL is not blocked by the immutability trigger of posted documents.
    op.add_column("stock_documents", sa.Column("price_rate", sa.Numeric(12, 4)))


def downgrade() -> None:
    op.drop_column("stock_documents", "price_rate")
    for name in ("ck_settings_rate", "ck_settings_rate_mode", "ck_settings_currency"):
        op.drop_constraint(name, "settings", type_="check")
    for col in ("rate_error", "rate_checked_at", "rate_updated_at", "rate_date", "rate_source", "rate_mode", "usd_krw_rate"):
        op.drop_column("settings", col)
    op.alter_column("settings", "currency", server_default="USD")
    op.alter_column("settings", "currency_decimals", server_default="2")
