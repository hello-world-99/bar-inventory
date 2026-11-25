"""POS sales imports and kitchen norms (agent-room replies 30-32)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

STATUS = ("draft", "posted", "covered", "voided")
# ck_products_unit_combo of 0002; 'pack' is compared as text: a new enum value cannot be used as a literal
# in the transaction that adds it.
UNIT_COMBO = (
    "(unit = 'ml'     AND base_unit = 'ml'  AND unit_size = 1)"
    " OR (unit = 'l'      AND base_unit = 'ml'  AND unit_size = 1000)"
    " OR (unit = 'bottle' AND base_unit = 'ml')"
    " OR (unit = 'g'      AND base_unit = 'g'   AND unit_size = 1)"
    " OR (unit = 'kg'     AND base_unit = 'g'   AND unit_size = 1000)"
    " OR (unit = 'pcs'    AND base_unit = 'pcs' AND unit_size = 1)"
)


def upgrade() -> None:
    # Usable only after this migration's transaction commits (env.py runs one transaction per migration).
    op.execute("ALTER TYPE write_off_reason ADD VALUE IF NOT EXISTS 'sales'")
    # Meat is counted in packs of 200 g and converted to grams (reply 37): a container unit like bottle/ml.
    op.execute("ALTER TYPE product_unit ADD VALUE IF NOT EXISTS 'pack'")
    op.drop_constraint("ck_products_unit_combo", "products", type_="check")
    op.create_check_constraint("ck_products_unit_combo", "products", UNIT_COMBO + " OR (unit::text = 'pack' AND base_unit = 'g')")
    pg.ENUM(*STATUS, name="sales_import_status").create(op.get_bind())

    op.create_table(
        "pos_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("not_kitchen", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("length(trim(code)) > 0", name="ck_pos_items_code"),
    )
    op.create_table(
        "pos_item_components",
        sa.Column("pos_item_id", sa.Integer, sa.ForeignKey("pos_items.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("products.id"), primary_key=True),
        sa.Column("qty_base", sa.Numeric(14, 3), nullable=False),
        sa.CheckConstraint("qty_base > 0", name="ck_pos_item_components_qty"),
    )
    op.create_index("ix_pos_item_components_product", "pos_item_components", ["product_id"])

    op.create_table(
        "sales_imports",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("sales_date", sa.Date, nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("status", pg.ENUM(*STATUS, name="sales_import_status", create_type=False), nullable=False, server_default="draft"),
        sa.Column("total_qty", sa.Numeric(14, 3), nullable=False),
        sa.Column("total_revenue", sa.Numeric(16, 2)),
        sa.Column("warnings", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("location_id", sa.Integer, sa.ForeignKey("locations.id")),
        sa.Column("write_off_id", sa.Uuid, sa.ForeignKey("stock_documents.id"), unique=True),
        sa.Column("covered_inventory_id", sa.Integer, sa.ForeignKey("inventories.id")),
        sa.Column("post_request_id", sa.Uuid),
        sa.Column("uploaded_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("closed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status <> 'posted' OR (write_off_id IS NOT NULL AND location_id IS NOT NULL)", name="ck_sales_imports_posted"),
        sa.CheckConstraint("status <> 'covered' OR (covered_inventory_id IS NOT NULL AND location_id IS NOT NULL)", name="ck_sales_imports_covered"),
    )
    # One active report per business day, and the same sales cannot be imported under two dates (reply 32, P1).
    op.create_index("uq_sales_imports_day_active", "sales_imports", ["sales_date"], unique=True,
                    postgresql_where=sa.text("status <> 'voided'"))
    op.create_index("uq_sales_imports_content_active", "sales_imports", ["content_sha256"], unique=True,
                    postgresql_where=sa.text("status <> 'voided'"))
    op.create_index("ix_sales_imports_location_date", "sales_imports", ["location_id", "sales_date"])

    op.create_table(
        "sales_import_lines",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("import_id", sa.Uuid, sa.ForeignKey("sales_imports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("line_no", sa.Integer, nullable=False),
        sa.Column("pos_code", sa.String(32), nullable=False),
        sa.Column("pos_name", sa.String(128), nullable=False),
        sa.Column("qty", sa.Numeric(14, 3), nullable=False),
        sa.Column("revenue", sa.Numeric(16, 2)),
        sa.UniqueConstraint("import_id", "pos_code", name="uq_sales_import_lines_code"),
    )
    op.create_table(
        "sales_import_usage",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("import_id", sa.Uuid, sa.ForeignKey("sales_imports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pos_code", sa.String(32), nullable=False),
        sa.Column("pos_name", sa.String(128), nullable=False),
        sa.Column("sold_qty", sa.Numeric(14, 3), nullable=False),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("per_unit_base", sa.Numeric(14, 3), nullable=False),
        sa.Column("qty_base", sa.Numeric(14, 3), nullable=False),
        sa.Column("covered_inventory_id", sa.Integer, sa.ForeignKey("inventories.id")),
        sa.Column("covered_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_sales_import_usage_import", "sales_import_usage", ["import_id"])


def downgrade() -> None:
    op.drop_table("sales_import_usage")
    op.drop_table("sales_import_lines")
    op.drop_table("sales_imports")
    op.drop_table("pos_item_components")
    op.drop_table("pos_items")
    pg.ENUM(name="sales_import_status").drop(op.get_bind())
    # Rebuild product_unit without 'pack' (fails while pack products exist); the check refers to the type, so it
    # is dropped first and recreated on the new type.
    op.drop_constraint("ck_products_unit_combo", "products", type_="check")
    op.execute("ALTER TYPE product_unit RENAME TO product_unit_old")
    op.execute("CREATE TYPE product_unit AS ENUM ('pcs', 'bottle', 'l', 'ml', 'kg', 'g')")
    op.execute("ALTER TABLE products ALTER COLUMN unit TYPE product_unit USING unit::text::product_unit")
    op.execute("DROP TYPE product_unit_old")
    op.create_check_constraint("ck_products_unit_combo", "products", UNIT_COMBO)
    # PostgreSQL cannot drop an enum value; rebuild the type without 'sales' (fails while such documents exist).
    op.execute("ALTER TYPE write_off_reason RENAME TO write_off_reason_old")
    op.execute("CREATE TYPE write_off_reason AS ENUM ('spoilage', 'expired', 'breakage', 'staff_use', 'other')")
    op.execute("ALTER TABLE stock_documents ALTER COLUMN reason TYPE write_off_reason USING reason::text::write_off_reason")
    op.execute("DROP TYPE write_off_reason_old")
