import { describe, expect, it } from "vitest";
import { formatQty, fromBase, inputUnits, plain, toBase, type Unit, type UnitInfo } from "./units";

const bottle: UnitInfo = { unit: "bottle", base_unit: "ml", unit_size: "700.000" };
const kg: UnitInfo = { unit: "kg", base_unit: "g", unit_size: "1000.000" };
const pcs: UnitInfo = { unit: "pcs", base_unit: "pcs", unit_size: "1.000" };
const short: Record<Unit, string> = { pcs: "pcs", bottle: "btl", l: "l", ml: "ml", kg: "kg", g: "g" };
const label = (u: Unit) => short[u];

describe("units", () => {
  it("converts bottles and ml both ways", () => {
    expect(toBase("2.5", "bottle", bottle).toString()).toBe("1750");
    expect(toBase("0.05", "l", bottle).toString()).toBe("50");
    expect(fromBase("350", "bottle", bottle).toString()).toBe("0.5");
  });

  it("rejects incompatible units", () => {
    expect(() => toBase("1", "kg", bottle)).toThrow();
    expect(() => toBase("1", "bottle", kg)).toThrow();
  });

  it("offers own, base and metric units", () => {
    expect(inputUnits(bottle)).toEqual(["bottle", "ml", "l"]);
    expect(inputUnits(kg)).toEqual(["kg", "g"]);
    expect(inputUnits(pcs)).toEqual(["pcs"]);
  });

  it("formats partially used bottles (700 ml bottle, 350 ml left)", () => {
    expect(formatQty("350", bottle, label)).toEqual({ main: "350 ml", alt: "0.5 btl" });
    expect(formatQty("1750", bottle, label)).toEqual({ main: "2 btl + 350 ml", alt: "2.5 btl" });
    expect(formatQty("1400", bottle, label)).toEqual({ main: "2 btl" });
    expect(formatQty("-350", bottle, label)).toEqual({ main: "−350 ml", alt: "−0.5 btl" });
    expect(formatQty("1", bottle, label)).toEqual({ main: "1 ml", alt: "< 0.01 btl" });
  });

  it("formats metric and piece units", () => {
    expect(formatQty("1250", kg, label).main).toBe("1.25 kg");
    expect(formatQty("3.000", pcs, label).main).toBe("3 pcs");
    expect(plain(toBase("0.0005", "kg", kg))).toBe("0.5");
  });
});
