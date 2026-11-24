"""Single source of truth for the role/permission matrix (docs/architecture.md section 6)."""

import enum

from app.models.user import Role


class Perm(str, enum.Enum):
    view = "view"  # dashboard, stock, catalog, journal
    manage_catalog = "manage_catalog"  # products, categories, locations
    post_receipt = "post_receipt"
    post_write_off = "post_write_off"
    post_transfer = "post_transfer"
    allow_negative = "allow_negative"
    backdate = "backdate"  # post a document dated before the last completed inventory
    reverse_document = "reverse_document"
    inventory_count = "inventory_count"  # start an inventory, enter counted quantities (blind)
    inventory_review = "inventory_review"  # see expected/discrepancies, complete, cancel
    manage_users = "manage_users"
    manage_settings = "manage_settings"


ROLE_PERMISSIONS: dict[Role, frozenset[Perm]] = {
    Role.admin: frozenset(Perm),
    Role.staff: frozenset(
        {
            Perm.view,
            Perm.post_receipt,
            Perm.post_write_off,
            Perm.post_transfer,
            Perm.inventory_count,
        }
    ),
}


def has_perm(role: Role, perm: Perm) -> bool:
    return perm in ROLE_PERMISSIONS.get(role, frozenset())
