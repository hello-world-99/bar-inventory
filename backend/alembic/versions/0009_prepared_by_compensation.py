"""POS reports: who prepared them; documents compensating a POS correction after an inventory (reply 48)

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sales_imports", sa.Column("prepared_by", sa.String(100)))
    # DDL only: the immutability trigger of posted documents is not involved.
    op.add_column("stock_documents", sa.Column("sales_import_id", sa.Uuid, sa.ForeignKey("sales_imports.id")))
    op.create_index("ix_stock_documents_sales_import", "stock_documents", ["sales_import_id"])


def downgrade() -> None:
    op.drop_index("ix_stock_documents_sales_import", table_name="stock_documents")
    op.drop_column("stock_documents", "sales_import_id")
    op.drop_column("sales_imports", "prepared_by")
