"""index movements by (product, location, doc_date)

Completion of an inventory computes the expected quantity as the sum of movements of a pair with
doc_date <= counted_at (docs/architecture.md section 5).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-25
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_movements_pair_doc_date", "stock_movements", ["product_id", "location_id", "doc_date"])


def downgrade() -> None:
    op.drop_index("ix_movements_pair_doc_date", table_name="stock_movements")
