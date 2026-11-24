/**
 * RFC 4122 version 4 UUID.
 *
 * Uses crypto.getRandomValues, which (unlike crypto.randomUUID) is available outside
 * secure contexts, e.g. when tablets open the app via http://192.168.x.x on the bar's LAN.
 */
export function uuidv4(rand: (buf: Uint8Array) => Uint8Array = (b) => crypto.getRandomValues(b)): string {
  const b = rand(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40; // version 4
  b[8] = (b[8] & 0x3f) | 0x80; // variant 10xx
  const hex = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
