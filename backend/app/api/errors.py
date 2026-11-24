from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

# Unique indexes that map to user-facing conflicts.
CONFLICT_MESSAGES = {
    "uq_products_sku_active": "An active product with this SKU already exists",
    "uq_products_barcode_active": "An active product with this barcode already exists",
    "uq_locations_name_active": "An active location with this name already exists",
    "uq_categories_name_active": "An active category with this name already exists",
    "uq_inventories_one_active_per_location": "This location already has an inventory in progress",
}


def constraint_name(err: IntegrityError) -> str | None:
    diag = getattr(err.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def integrity_to_http(err: IntegrityError) -> HTTPException:
    name = constraint_name(err)
    if name in CONFLICT_MESSAGES:
        return HTTPException(status.HTTP_409_CONFLICT, CONFLICT_MESSAGES[name])
    return HTTPException(status.HTTP_409_CONFLICT, f"Conflicts with existing data ({name or 'constraint'})")
