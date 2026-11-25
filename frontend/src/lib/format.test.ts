import { describe, expect, it } from "vitest";
import { moneyFormat } from "./format";

describe("money (stored in won, shown in KRW or USD at the rate)", () => {
  it("won by default, no decimals", () => {
    const c = moneyFormat({ currency: "KRW", currency_decimals: 0, usd_krw_rate: null }, "en");
    expect(c.code).toBe("KRW");
    expect(c.format(c.toDisplay("2971000"))).toBe("₩2,971,000");
    expect(c.format(c.toDisplay("19600.4"))).toBe("₩19,600");
  });

  it("dollars at the current rate, two decimals", () => {
    const c = moneyFormat({ currency: "USD", currency_decimals: 2, usd_krw_rate: "1400.0000" }, "en");
    expect(c.code).toBe("USD");
    expect(c.toDisplay("19600").toString()).toBe("14");
    expect(c.format(c.toDisplay("19600"))).toBe("$14.00");
    expect(c.format(c.toDisplay("2971000"))).toBe("$2,122.14");
  });

  it("dollars without a rate fall back to won rather than showing wrong numbers", () => {
    const c = moneyFormat({ currency: "USD", currency_decimals: 2, usd_krw_rate: null }, "en");
    expect(c.code).toBe("KRW");
    expect(c.format(c.toDisplay("1000"))).toBe("₩1,000");
  });
});
