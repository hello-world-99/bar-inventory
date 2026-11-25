"""Unit rules from docs/architecture.md section 2. All quantities are stored in the product's base unit."""

from decimal import ROUND_HALF_UP, Decimal

from app.models.catalog import BaseUnit, Unit

QTY_QUANT = Decimal("0.001")  # NUMERIC(14,3)

BASE_OF: dict[Unit, BaseUnit] = {
    Unit.ml: BaseUnit.ml,
    Unit.l: BaseUnit.ml,
    Unit.bottle: BaseUnit.ml,
    Unit.pack: BaseUnit.g,
    Unit.g: BaseUnit.g,
    Unit.kg: BaseUnit.g,
    Unit.pcs: BaseUnit.pcs,
}

FIXED_SIZE: dict[Unit, Decimal] = {
    Unit.ml: Decimal(1),
    Unit.l: Decimal(1000),
    Unit.g: Decimal(1),
    Unit.kg: Decimal(1000),
    Unit.pcs: Decimal(1),
}


class UnitError(ValueError):
    pass


# Containers: a bottle of N ml, a pack of N g. Their size is set per product; the unit itself is meaningful only
# for products counted in it (a "bottle" of flour is not a thing).
CONTAINERS: dict[Unit, str] = {Unit.bottle: "Bottle size (ml)", Unit.pack: "Pack size (g)"}


def resolve_unit_size(unit: Unit, unit_size: Decimal | None) -> Decimal:
    """unit_size is user-defined only for containers (bottles, packs); every other unit has a fixed size."""
    if unit in CONTAINERS:
        if unit_size is None or unit_size <= 0:
            raise UnitError(f"{CONTAINERS[unit]} is required and must be positive")
        return unit_size.quantize(QTY_QUANT)
    fixed = FIXED_SIZE[unit]
    if unit_size is not None and unit_size != fixed:
        raise UnitError(f"Size of unit '{unit.value}' is fixed at {fixed}")
    return fixed


def factor(qty_unit: Unit, product_unit: Unit, base_unit: BaseUnit, unit_size: Decimal) -> Decimal:
    """How many base units one `qty_unit` holds for this product.

    Accepted: the product's own unit, its base unit, and the metric unit of the same base (l for ml, kg for g).
    A bottle (pack) is only meaningful for bottle (pack) products.
    """
    if qty_unit == product_unit:
        return unit_size
    if BASE_OF[qty_unit] != base_unit or qty_unit in CONTAINERS:
        raise UnitError(f"Quantity in '{qty_unit.value}' is not compatible with a product measured in '{product_unit.value}'")
    return FIXED_SIZE[qty_unit]


def to_base(qty: Decimal, qty_unit: Unit, product_unit: Unit, base_unit: BaseUnit, unit_size: Decimal) -> Decimal:
    value = (qty * factor(qty_unit, product_unit, base_unit, unit_size)).quantize(QTY_QUANT, ROUND_HALF_UP)
    return value
