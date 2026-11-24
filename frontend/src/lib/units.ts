import Big from "big.js";

export type Unit = "pcs" | "bottle" | "l" | "ml" | "kg" | "g";
export type BaseUnit = "ml" | "g" | "pcs";

export interface UnitInfo {
  unit: Unit;
  base_unit: BaseUnit;
  unit_size: string; // decimal string, base units per `unit`
}

export const UNITS: Unit[] = ["pcs", "bottle", "l", "ml", "kg", "g"];

export const BASE_OF: Record<Unit, BaseUnit> = { pcs: "pcs", bottle: "ml", l: "ml", ml: "ml", kg: "g", g: "g" };

const FIXED: Partial<Record<Unit, number>> = { pcs: 1, l: 1000, ml: 1, kg: 1000, g: 1 };

/** Units in which a quantity of this product may be entered (mirrors backend app/core/units.py). */
export function inputUnits(p: UnitInfo): Unit[] {
  const metric: Record<BaseUnit, Unit[]> = { ml: ["ml", "l"], g: ["g", "kg"], pcs: ["pcs"] };
  return Array.from(new Set<Unit>([p.unit, ...metric[p.base_unit]]));
}

/** Base units held by one `qtyUnit` of this product. */
export function factor(qtyUnit: Unit, p: UnitInfo): Big {
  if (qtyUnit === p.unit) return new Big(p.unit_size);
  if (BASE_OF[qtyUnit] !== p.base_unit || qtyUnit === "bottle") throw new Error(`Unit ${qtyUnit} not compatible`);
  return new Big(FIXED[qtyUnit]!);
}

export function toBase(qty: string, qtyUnit: Unit, p: UnitInfo): Big {
  return new Big(qty).times(factor(qtyUnit, p)).round(3, Big.roundHalfUp);
}

export function fromBase(qtyBase: string, qtyUnit: Unit, p: UnitInfo, dp = 3): Big {
  return new Big(qtyBase).div(factor(qtyUnit, p)).round(dp, Big.roundHalfUp);
}

/** Trim trailing zeros: "2.500" -> "2.5", "3.000" -> "3". */
export function plain(b: Big, dp = 3): string {
  const s = b.round(dp, Big.roundHalfUp).toFixed(dp);
  return s.includes(".") ? s.replace(/\.?0+$/, "") : s;
}

export interface QtyParts {
  /** e.g. "2 btl + 350 ml" for bottles, "1.25 l" otherwise */
  main: string;
  /** e.g. "2.5 btl" for partial bottles; undefined when it would repeat `main` */
  alt?: string;
}

/**
 * Human-readable quantity. Partially used bottles are shown as full bottles plus the open one in ml,
 * with the fractional bottle count as an alternative (requirements section 3).
 */
export function formatQty(qtyBase: string, p: UnitInfo, label: (u: Unit) => string): QtyParts {
  const q = new Big(qtyBase);
  const neg = q.lt(0);
  const abs = q.abs();
  const sign = neg ? "−" : "";
  if (p.unit === "bottle") {
    const size = new Big(p.unit_size);
    const full = abs.div(size).round(0, Big.roundDown);
    const rest = abs.minus(full.times(size));
    const frac = plain(abs.div(size), 2);
    // A few ml would round to "0 btl"; say "< 0.01 btl" instead of something that reads as empty.
    const bottles = frac === "0" ? `${sign}< 0.01 ${label("bottle")}` : `${sign}${frac} ${label("bottle")}`;
    if (rest.eq(0)) return { main: `${sign}${full.toFixed(0)} ${label("bottle")}` };
    if (full.eq(0)) return { main: `${sign}${plain(rest)} ${label("ml")}`, alt: bottles };
    return { main: `${sign}${full.toFixed(0)} ${label("bottle")} + ${plain(rest)} ${label("ml")}`, alt: bottles };
  }
  return { main: `${sign}${plain(fromBase(abs.toString(), p.unit, p))} ${label(p.unit)}` };
}
