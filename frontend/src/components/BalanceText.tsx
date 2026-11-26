import Big from "big.js";
import { useQty } from "@/lib/format";
import type { UnitInfo } from "@/lib/units";

/** A stock balance, red when the product is at or below its minimum or negative — one format everywhere
 * (journal, document card, forms, POS report; owner: "show the balance everywhere"). */
export function BalanceText({ qtyBase, unit, min, low: flagged }: { qtyBase: string; unit: UnitInfo; min?: string | null; low?: boolean }) {
  const qty = useQty();
  const b = new Big(qtyBase);
  // `low` comes from the caller when "running out" is decided on the total over all places (reply 75)
  const low = flagged || b.lt(0) || (min != null && new Big(min).gt(0) && b.lte(min));
  return <span className={`tabular-nums ${low ? "font-semibold text-red-700" : "text-zinc-700"}`}>{qty(qtyBase, unit).main}</span>;
}
