"""catalog, stock documents, movement journal, inventories (docs/architecture.md sections 2-5)

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

ENUMS = {
    "product_unit": ("pcs", "bottle", "l", "ml", "kg", "g"),
    "base_unit": ("ml", "g", "pcs"),
    "doc_type": ("receipt", "write_off", "transfer", "inventory_adjustment", "reversal"),
    "doc_status": ("draft", "posted"),
    "write_off_reason": ("spoilage", "expired", "breakage", "staff_use", "other"),
    "inventory_status": ("in_progress", "completed", "cancelled"),
}

SEED_CATEGORIES = [
    ("alcohol", "Alcohol"),
    ("soft_drinks", "Soft drinks"),
    ("food_ingredients", "Food & ingredients"),
    ("supplies", "Supplies"),
    ("other", "Other"),
]


def E(name: str) -> pg.ENUM:
    return pg.ENUM(*ENUMS[name], name=name, create_type=False)


def ts(name: str, nullable: bool = False, default: bool = False) -> sa.Column:
    return sa.Column(
        name, sa.DateTime(timezone=True), nullable=nullable, server_default=sa.func.now() if default else None
    )


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in ENUMS.items():
        pg.ENUM(*values, name=name).create(bind)

    # ---------------------------------------------------------------- catalog
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String(32), unique=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        ts("created_at", default=True),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_categories_name"),
    )
    op.create_index(
        "uq_categories_name_active", "categories", [sa.text("lower(name)")], unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.bulk_insert(
        sa.table("categories", sa.column("code"), sa.column("name")),
        [{"code": c, "name": n} for c, n in SEED_CATEGORIES],
    )

    op.create_table(
        "locations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.String(255), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        ts("created_at", default=True),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_locations_name"),
    )
    op.create_index(
        "uq_locations_name_active", "locations", [sa.text("lower(name)")], unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "products",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("sku", sa.String(64), nullable=False),
        sa.Column("category_id", sa.Integer, sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("unit", E("product_unit"), nullable=False),
        sa.Column("base_unit", E("base_unit"), nullable=False),
        sa.Column("unit_size", sa.Numeric(14, 3), nullable=False),
        sa.Column("purchase_price", sa.Numeric(14, 2), nullable=False, server_default="0"),
        ts("price_updated_at", nullable=True),
        sa.Column("min_stock_base", sa.Numeric(14, 3), nullable=False, server_default="0"),
        sa.Column("barcode", sa.String(64)),
        sa.Column("full_weight_g", sa.Numeric(10, 1)),
        sa.Column("empty_weight_g", sa.Numeric(10, 1)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        ts("created_at", default=True),
        ts("updated_at", default=True),
        sa.CheckConstraint("length(trim(name)) > 0 AND length(trim(sku)) > 0", name="ck_products_name_sku"),
        sa.CheckConstraint("purchase_price >= 0", name="ck_products_price"),
        sa.CheckConstraint("min_stock_base >= 0", name="ck_products_min_stock"),
        sa.CheckConstraint("unit_size > 0", name="ck_products_unit_size_positive"),
        # docs/architecture.md section 2: allowed unit/base_unit pairs and fixed sizes.
        sa.CheckConstraint(
            "(unit = 'ml'     AND base_unit = 'ml'  AND unit_size = 1)"
            " OR (unit = 'l'      AND base_unit = 'ml'  AND unit_size = 1000)"
            " OR (unit = 'bottle' AND base_unit = 'ml')"
            " OR (unit = 'g'      AND base_unit = 'g'   AND unit_size = 1)"
            " OR (unit = 'kg'     AND base_unit = 'g'   AND unit_size = 1000)"
            " OR (unit = 'pcs'    AND base_unit = 'pcs' AND unit_size = 1)",
            name="ck_products_unit_combo",
        ),
        sa.CheckConstraint(
            "(full_weight_g IS NULL OR full_weight_g > 0)"
            " AND (empty_weight_g IS NULL OR empty_weight_g >= 0)"
            " AND (full_weight_g IS NULL OR empty_weight_g IS NULL OR full_weight_g > empty_weight_g)",
            name="ck_products_weights",
        ),
    )
    op.create_index(
        "uq_products_sku_active", "products", [sa.text("lower(sku)")], unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_index(
        "uq_products_barcode_active", "products", ["barcode"], unique=True,
        postgresql_where=sa.text("is_active AND barcode IS NOT NULL"),
    )
    op.create_index("ix_products_category", "products", ["category_id"])

    # ------------------------------------------------------------------ stock
    op.create_table(
        "stock_balances",
        sa.Column("product_id", sa.Integer, sa.ForeignKey("products.id"), primary_key=True),
        sa.Column("location_id", sa.Integer, sa.ForeignKey("locations.id"), primary_key=True),
        sa.Column("qty_base", sa.Numeric(14, 3), nullable=False, server_default="0"),
        ts("updated_at", default=True),
    )
    op.create_index("ix_stock_balances_location", "stock_balances", ["location_id"])

    op.create_table(
        "stock_documents",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("type", E("doc_type"), nullable=False),
        sa.Column("status", E("doc_status"), nullable=False, server_default="draft"),
        ts("doc_date"),
        sa.Column("reason", E("write_off_reason")),
        sa.Column("supplier", sa.String(128)),
        sa.Column("invoice_no", sa.String(64)),
        sa.Column("comment", sa.Text, nullable=False, server_default=""),
        sa.Column("reversal_of", sa.Uuid, sa.ForeignKey("stock_documents.id"), unique=True),
        sa.Column("allow_negative", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("backdate_confirmed", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        ts("created_at", default=True),
        sa.Column("posted_by", sa.Integer, sa.ForeignKey("users.id")),
        ts("posted_at", nullable=True),
        sa.CheckConstraint("(type = 'write_off') = (reason IS NOT NULL)", name="ck_docs_reason_iff_write_off"),
        sa.CheckConstraint("(type = 'reversal') = (reversal_of IS NOT NULL)", name="ck_docs_reversal_of_iff_reversal"),
        sa.CheckConstraint("reversal_of IS NULL OR reversal_of <> id", name="ck_docs_not_self_reversal"),
        sa.CheckConstraint(
            "(status = 'draft' AND posted_at IS NULL AND posted_by IS NULL)"
            " OR (status = 'posted' AND posted_at IS NOT NULL AND posted_by IS NOT NULL)",
            name="ck_docs_posted_fields",
        ),
    )
    op.create_index("ix_stock_documents_type_date", "stock_documents", ["type", "doc_date"])
    op.create_index("ix_stock_documents_doc_date", "stock_documents", ["doc_date"])

    op.create_table(
        "stock_document_lines",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("document_id", sa.Uuid, sa.ForeignKey("stock_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("line_no", sa.Integer, nullable=False),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("location_from_id", sa.Integer, sa.ForeignKey("locations.id")),
        sa.Column("location_to_id", sa.Integer, sa.ForeignKey("locations.id")),
        sa.Column("qty_base", sa.Numeric(14, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(14, 2)),
        sa.Column("unit_cost_base", sa.Numeric(18, 6)),
        sa.UniqueConstraint("document_id", "line_no", name="uq_doc_lines_line_no"),
        sa.CheckConstraint("qty_base <> 0", name="ck_doc_lines_qty_nonzero"),
        sa.CheckConstraint(
            "location_from_id IS NOT NULL OR location_to_id IS NOT NULL", name="ck_doc_lines_has_location"
        ),
        sa.CheckConstraint(
            "location_from_id IS NULL OR location_to_id IS NULL OR location_from_id <> location_to_id",
            name="ck_doc_lines_from_ne_to",
        ),
        sa.CheckConstraint("unit_price IS NULL OR unit_price >= 0", name="ck_doc_lines_price"),
        sa.CheckConstraint("unit_cost_base IS NULL OR unit_cost_base >= 0", name="ck_doc_lines_cost"),
    )
    op.create_index("ix_doc_lines_document", "stock_document_lines", ["document_id"])
    op.create_index("ix_doc_lines_product", "stock_document_lines", ["product_id"])

    op.create_table(
        "stock_movements",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("document_id", sa.Uuid, sa.ForeignKey("stock_documents.id"), nullable=False),
        sa.Column("product_id", sa.Integer, nullable=False),
        sa.Column("location_id", sa.Integer, nullable=False),
        sa.Column("delta_base", sa.Numeric(14, 3), nullable=False),
        sa.Column("unit_cost_base", sa.Numeric(18, 6), nullable=False),
        sa.Column("balance_after", sa.Numeric(14, 3), nullable=False),
        ts("doc_date"),
        ts("created_at", default=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        # Every movement belongs to an existing balance row (which also pins product and location).
        sa.ForeignKeyConstraint(
            ["product_id", "location_id"],
            ["stock_balances.product_id", "stock_balances.location_id"],
            name="fk_movements_balance",
        ),
        sa.CheckConstraint("delta_base <> 0", name="ck_movements_delta_nonzero"),
        sa.CheckConstraint("unit_cost_base >= 0", name="ck_movements_cost"),
    )
    op.create_index("ix_movements_pair_created", "stock_movements", ["product_id", "location_id", "created_at"])
    op.create_index("ix_movements_doc_date", "stock_movements", ["doc_date"])
    op.create_index("ix_movements_document", "stock_movements", ["document_id"])
    op.create_index("ix_movements_location", "stock_movements", ["location_id"])

    # The journal is append-only. TRUNCATE (used by tests) does not fire row triggers.
    op.execute(
        """
        CREATE FUNCTION stock_movements_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'stock_movements is append-only (% rejected)', TG_OP
            USING ERRCODE = 'restrict_violation';
        END $$;
        CREATE TRIGGER trg_stock_movements_append_only
          BEFORE UPDATE OR DELETE ON stock_movements
          FOR EACH ROW EXECUTE FUNCTION stock_movements_append_only();
        """
    )

    # Posted documents are immutable: the only allowed transition is draft -> posted, and lines can
    # only change while the parent is a draft. Services must insert lines BEFORE flipping the status.
    op.execute(
        """
        CREATE FUNCTION stock_documents_posted_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.status = 'posted' THEN
            RAISE EXCEPTION 'posted stock document % is immutable (% rejected)', OLD.id, TG_OP
              USING ERRCODE = 'restrict_violation';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER trg_stock_documents_posted_immutable
          BEFORE UPDATE OR DELETE ON stock_documents
          FOR EACH ROW EXECUTE FUNCTION stock_documents_posted_immutable();

        CREATE FUNCTION stock_document_lines_draft_only() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          parent_status doc_status;
        BEGIN
          SELECT status INTO parent_status FROM stock_documents
           WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.document_id ELSE NEW.document_id END;
          IF parent_status = 'posted'
             OR (TG_OP = 'UPDATE' AND OLD.document_id <> NEW.document_id
                 AND (SELECT status FROM stock_documents WHERE id = OLD.document_id) = 'posted') THEN
            RAISE EXCEPTION 'lines of a posted stock document are immutable (% rejected)', TG_OP
              USING ERRCODE = 'restrict_violation';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER trg_stock_document_lines_draft_only
          BEFORE INSERT OR UPDATE OR DELETE ON stock_document_lines
          FOR EACH ROW EXECUTE FUNCTION stock_document_lines_draft_only();
        """
    )

    # -------------------------------------------------------------- inventory
    op.create_table(
        "inventories",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("location_id", sa.Integer, sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("status", E("inventory_status"), nullable=False, server_default="in_progress"),
        sa.Column("comment", sa.Text, nullable=False, server_default=""),
        sa.Column("started_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        ts("started_at", default=True),
        sa.Column("completed_by", sa.Integer, sa.ForeignKey("users.id")),
        ts("completed_at", nullable=True),
        sa.Column("adjustment_document_id", sa.Uuid, sa.ForeignKey("stock_documents.id"), unique=True),
        sa.CheckConstraint(
            "(status = 'in_progress' AND completed_at IS NULL AND completed_by IS NULL)"
            " OR (status <> 'in_progress' AND completed_at IS NOT NULL AND completed_by IS NOT NULL)",
            name="ck_inventories_closed_fields",
        ),
        sa.CheckConstraint(
            "adjustment_document_id IS NULL OR status = 'completed'", name="ck_inventories_adjustment_only_completed"
        ),
    )
    op.create_index(
        "uq_inventories_one_active_per_location", "inventories", ["location_id"], unique=True,
        postgresql_where=sa.text("status = 'in_progress'"),
    )
    op.create_index("ix_inventories_location_completed", "inventories", ["location_id", "completed_at"])

    op.create_table(
        "inventory_lines",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("inventory_id", sa.Integer, sa.ForeignKey("inventories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("expected_at_start_base", sa.Numeric(14, 3), nullable=False),
        sa.Column("counted_base", sa.Numeric(14, 3)),
        sa.Column("expected_at_count_base", sa.Numeric(14, 3)),
        ts("counted_at", nullable=True),
        sa.Column("counted_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("unit_cost_base", sa.Numeric(18, 6)),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.UniqueConstraint("inventory_id", "product_id", name="uq_inventory_lines_product"),
        sa.CheckConstraint("counted_base IS NULL OR counted_base >= 0", name="ck_inventory_lines_counted"),
        # A line is either untouched or fully counted.
        sa.CheckConstraint(
            "(counted_base IS NULL AND expected_at_count_base IS NULL AND counted_at IS NULL AND counted_by IS NULL)"
            " OR (counted_base IS NOT NULL AND expected_at_count_base IS NOT NULL"
            "     AND counted_at IS NOT NULL AND counted_by IS NOT NULL)",
            name="ck_inventory_lines_count_fields",
        ),
    )
    op.create_index("ix_inventory_lines_product", "inventory_lines", ["product_id"])


def downgrade() -> None:
    op.drop_table("inventory_lines")
    op.drop_table("inventories")
    op.execute("DROP TRIGGER IF EXISTS trg_stock_movements_append_only ON stock_movements")
    op.execute("DROP FUNCTION IF EXISTS stock_movements_append_only()")
    op.drop_table("stock_movements")
    op.execute("DROP TRIGGER IF EXISTS trg_stock_document_lines_draft_only ON stock_document_lines")
    op.execute("DROP FUNCTION IF EXISTS stock_document_lines_draft_only()")
    op.drop_table("stock_document_lines")
    op.execute("DROP TRIGGER IF EXISTS trg_stock_documents_posted_immutable ON stock_documents")
    op.execute("DROP FUNCTION IF EXISTS stock_documents_posted_immutable()")
    op.drop_table("stock_documents")
    op.drop_table("stock_balances")
    op.drop_table("products")
    op.drop_table("locations")
    op.drop_table("categories")
    bind = op.get_bind()
    for name in reversed(list(ENUMS)):
        pg.ENUM(name=name).drop(bind, checkfirst=True)
