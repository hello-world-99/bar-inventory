"""users and settings

Revision ID: 0001
Revises:
Create Date: 2026-11-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    user_role = sa.Enum("admin", "staff", name="user_role")
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("full_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("token_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("uq_users_username_lower", "users", [sa.text("lower(username)")], unique=True)

    op.create_table(
        "settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("venue_name", sa.String(128), nullable=False, server_default="My Bar"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("currency_decimals", sa.SmallInteger, nullable=False, server_default="2"),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("business_day_starts_at", sa.Time, nullable=False, server_default="06:00"),
        sa.Column("blind_count", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.CheckConstraint("id = 1", name="settings_singleton"),
    )
    op.execute("INSERT INTO settings (id) VALUES (1)")


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_index("uq_users_username_lower", table_name="users")
    op.drop_table("users")
    sa.Enum(name="user_role").drop(op.get_bind(), checkfirst=True)
