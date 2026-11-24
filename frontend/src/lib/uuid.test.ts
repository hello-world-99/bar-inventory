import { describe, expect, it } from "vitest";
import { uuidv4 } from "./uuid";

describe("uuidv4", () => {
  it("produces RFC 4122 v4 format", () => {
    for (let i = 0; i < 100; i++) {
      expect(uuidv4()).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    }
  });

  it("sets version and variant bits regardless of random input", () => {
    expect(uuidv4((b) => b.fill(0xff))).toBe("ffffffff-ffff-4fff-bfff-ffffffffffff");
    expect(uuidv4((b) => b.fill(0x00))).toBe("00000000-0000-4000-8000-000000000000");
  });

  it("is unique across many calls", () => {
    const set = new Set(Array.from({ length: 1000 }, () => uuidv4()));
    expect(set.size).toBe(1000);
  });
});
