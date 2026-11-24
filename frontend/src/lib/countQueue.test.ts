import { describe, expect, it } from "vitest";
import { enqueue, loadQueue, settle, toRequest, type KV, type PendingCount } from "./countQueue";

function memory(): KV {
  const m = new Map<string, string>();
  return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => void m.set(k, v) };
}

let n = 0;
const item = (productId: number, qty: string, userId = 1): PendingCount => ({
  key: `7:${productId}`,
  entryId: `e${++n}`,
  userId,
  inventoryId: 7,
  productId,
  parts: [{ qty, qty_unit: "bottle" }],
  countedAt: "2026-11-25T21:00:00.000Z",
  version: 2,
});

describe("pending count queue", () => {
  it("keeps only the latest count per line and survives reloads", () => {
    const kv = memory();
    enqueue(item(1, "2"), kv);
    const b = item(2, "5");
    enqueue(b, kv);
    enqueue(item(1, "3"), kv);
    expect(loadQueue(1, 7, kv).map((x) => [x.productId, x.parts[0].qty])).toEqual([[2, "5"], [1, "3"]]);
    settle(b, 3, kv);
    expect(loadQueue(1, 7, kv).map((x) => x.productId)).toEqual([1]);
  });

  it("an answer to an older upload keeps the newer input and hands it the new version", () => {
    const kv = memory();
    const a = item(1, "5");
    enqueue(a, kv); // A is in flight...
    enqueue(item(1, "4"), kv); // ...and the person corrects it to 4
    settle(a, 3, kv); // 200 for A, line is now at version 3
    const q = loadQueue(1, 7, kv);
    expect(q.map((x) => [x.parts[0].qty, x.version])).toEqual([["4", 3]]);
  });

  it("a rejected older upload does not drop the newer input", () => {
    const kv = memory();
    const a = item(1, "5");
    enqueue(a, kv);
    enqueue(item(1, "4"), kv);
    settle(a, null, kv);
    expect(loadQueue(1, 7, kv).map((x) => [x.parts[0].qty, x.version])).toEqual([["4", 2]]);
  });

  it("each user sees and sends only their own counts", () => {
    const kv = memory();
    enqueue(item(1, "5", 1), kv);
    enqueue(item(1, "6", 2), kv);
    expect(loadQueue(1, undefined, kv).map((x) => x.parts[0].qty)).toEqual(["5"]);
    expect(loadQueue(2, 7, kv).map((x) => x.parts[0].qty)).toEqual(["6"]);
  });

  it("sends the counting time and the sending time separately", () => {
    const r = toRequest(item(1, "2"), new Date("2026-11-25T21:20:00.000Z"));
    expect(r.counted_at).toBe("2026-11-25T21:00:00.000Z");
    expect(r.sent_at).toBe("2026-11-25T21:20:00.000Z");
    expect(r.version).toBe(2);
  });

  it("tolerates missing or corrupt storage", () => {
    expect(loadQueue(1, undefined, null)).toEqual([]);
    const kv = memory();
    kv.setItem("bar-inventory.pending-counts.v2", "{not json");
    expect(loadQueue(1, undefined, kv)).toEqual([]);
  });
});
