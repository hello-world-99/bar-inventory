"""cost per base unit used for each written-off product of a POS report (owner: editable cost)

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sales_import_usage", sa.Column("unit_cost_base", sa.Numeric(18, 6)))


def downgrade() -> None:
    op.drop_column("sales_import_usage", "unit_cost_base")
