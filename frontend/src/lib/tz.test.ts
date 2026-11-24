import { describe, expect, it } from "vitest";
import { nowLocalIn, tzOffsetMinutes, zonedLocalToIso } from "./tz";

describe("time zone conversion (independent of the device time zone)", () => {
  it("reads a form value in the installation's zone", () => {
    expect(zonedLocalToIso("2026-11-25T21:00", "Asia/Seoul")).toBe("2026-11-25T12:00:00.000Z");
    expect(zonedLocalToIso("2026-11-25T21:00", "UTC")).toBe("2026-11-25T21:00:00.000Z");
    expect(zonedLocalToIso("2026-11-25T21:00", "Europe/Moscow")).toBe("2026-11-25T18:00:00.000Z");
  });

  it("handles daylight saving time", () => {
    expect(zonedLocalToIso("2026-07-01T12:00", "America/New_York")).toBe("2026-07-01T16:00:00.000Z"); // EDT -4
    expect(zonedLocalToIso("2026-12-01T12:00", "America/New_York")).toBe("2026-12-01T17:00:00.000Z"); // EST -5
    expect(zonedLocalToIso("2026-11-01T01:30", "America/New_York")).toMatch(/^2026-11-01T0[56]:30:00.000Z$/); // ambiguous hour
  });

  it("computes offsets and the current local time", () => {
    expect(tzOffsetMinutes(Date.UTC(2026, 0, 1), "Asia/Kolkata")).toBe(330);
    expect(nowLocalIn("Asia/Seoul", Date.UTC(2026, 10, 25, 12, 0))).toBe("2026-11-25T21:00");
  });
});
