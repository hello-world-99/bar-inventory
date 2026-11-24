/**
 * Wall-clock times are entered and shown in the installation's time zone (settings.timezone), not the
 * device's: cheap tablets often run in UTC, and since doc_date decides whether a stock count already
 * contains a document, a 9-hour shift would change stock, not just a label. No dependency: Intl only.
 */

/** Offset of `timeZone` from UTC, in minutes, at the instant `utcMs`. */
export function tzOffsetMinutes(utcMs: number, timeZone: string): number {
  const name =
    new Intl.DateTimeFormat("en-US", { timeZone, timeZoneName: "longOffset" })
      .formatToParts(new Date(utcMs))
      .find((p) => p.type === "timeZoneName")?.value ?? "GMT";
  const m = /GMT([+-])(\d{1,2})(?::?(\d{2}))?/.exec(name);
  if (!m) return 0; // "GMT" = UTC
  return (m[1] === "-" ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3] ?? 0));
}

/** "2026-11-25T21:00" as a wall-clock time in `timeZone` -> ISO instant ("2026-11-25T12:00:00.000Z" for Asia/Seoul). */
export function zonedLocalToIso(local: string, timeZone: string): string {
  const [d, t = "00:00"] = local.split("T");
  const [y, mo, da] = d.split("-").map(Number);
  const [h, mi, s = 0] = t.split(":").map(Number);
  const guess = Date.UTC(y, mo - 1, da, h, mi, s);
  const off1 = tzOffsetMinutes(guess, timeZone);
  let utc = guess - off1 * 60_000;
  const off2 = tzOffsetMinutes(utc, timeZone); // differs only around a DST switch
  if (off2 !== off1) utc = guess - off2 * 60_000;
  return new Date(utc).toISOString();
}

/** Current wall-clock time in `timeZone` as "YYYY-MM-DDTHH:mm" (for datetime-local max/defaults). */
export function nowLocalIn(timeZone: string, now = Date.now()): string {
  return new Date(now + tzOffsetMinutes(now, timeZone) * 60_000).toISOString().slice(0, 16);
}
