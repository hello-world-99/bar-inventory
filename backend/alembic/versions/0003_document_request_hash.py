"""request hash for idempotent document creation

A retried POST with the same client UUID and the same body returns the existing document;
the same UUID with a different body is a conflict. The hash of the canonical request decides.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # stock_documents has an immutability trigger for posted rows; adding a column is DDL and unaffected.
    op.add_column("stock_documents", sa.Column("request_hash", sa.String(64)))


def downgrade() -> None:
    op.drop_column("stock_documents", "request_hash")
