"""kitchen products and POS norms confirmed by the owner (agent-room replies 30 and 32)

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-25
"""

from alembic import op

from app.services.kitchen_seed import seed

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    seed(op.get_bind())


def downgrade() -> None:
    # Seeded rows are ordinary catalog data the owner may have used by now; they are not removed.
    pass
