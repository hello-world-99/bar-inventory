/**
 * Offline buffer for inventory counts (architecture section 5): a count is stored with the moment the
 * person pressed "Save" (counted_at, device clock) and sent with sent_at (device clock at upload), so the
 * server can correct the device's clock error while keeping the real counting time. Survives reloads.
 *
 * One entry per line (the newest input wins). Every entry has its own entryId, so an answer to an older
 * upload never removes a newer input of the same line; the newer input inherits the line version from
 * that answer (it is the same device's input, not a colleague's). Entries belong to the user who made
 * them: a shared tablet sends only the signed-in person's counts.
 */

export interface PendingCount {
  key: string; // `${inventoryId}:${productId}` - a newer count of the same line replaces the older one
  entryId: string;
  userId: number;
  inventoryId: number;
  productId: number;
  parts: { qty: string; qty_unit: string }[];
  countedAt: string; // ISO, device clock
  version: number | null;
}

const STORAGE_KEY = "bar-inventory.pending-counts.v2";

export interface KV {
  getItem(k: string): string | null;
  setItem(k: string, v: string): void;
}

function storage(): KV | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function loadAll(kv: KV | null): PendingCount[] {
  try {
    const raw = kv?.getItem(STORAGE_KEY);
    const q = raw ? (JSON.parse(raw) as PendingCount[]) : [];
    return Array.isArray(q) ? q : [];
  } catch {
    return [];
  }
}

function save(q: PendingCount[], kv: KV | null) {
  try {
    kv?.setItem(STORAGE_KEY, JSON.stringify(q));
  } catch {
    /* storage full or unavailable: the in-memory attempt still runs */
  }
}

/** Pending counts of one user (all of them, or of one inventory). */
export function loadQueue(userId: number, inventoryId?: number, kv: KV | null = storage()): PendingCount[] {
  return loadAll(kv).filter((x) => x.userId === userId && (inventoryId === undefined || x.inventoryId === inventoryId));
}

export function enqueue(item: PendingCount, kv: KV | null = storage()): void {
  const q = loadAll(kv).filter((x) => !(x.key === item.key && x.userId === item.userId));
  q.push(item);
  save(q, kv);
}

/**
 * The upload of `sent` got a definite answer. Removes it if it is still the queued entry; if a newer
 * input of the same line was queued meanwhile, keeps that one and, on success, gives it the new version.
 */
export function settle(sent: PendingCount, newVersion: number | null, kv: KV | null = storage()): void {
  const q: PendingCount[] = [];
  for (const x of loadAll(kv)) {
    if (x.entryId === sent.entryId) continue;
    if (x.key === sent.key && x.userId === sent.userId && newVersion !== null) q.push({ ...x, version: newVersion });
    else q.push(x);
  }
  save(q, kv);
}

/**
 * Whether an answer to an upload is final for that entry. Network errors (status 0), 5xx, 429 and 401 are
 * not: 401 means the session ended (expired refresh token, password or role changed), and the entry
 * belongs to its user, so it is sent once that person signs in again. Other 4xx (403 no longer allowed,
 * 409 version conflict / count closed, 422 invalid) will not change on retry.
 */
export function isDefinite(status: number): boolean {
  return status >= 400 && status < 500 && status !== 401 && status !== 429;
}

/** Body for PUT /inventories/{id}/lines/{product}; sent_at is taken at the moment of sending. */
export function toRequest(item: PendingCount, sentAt: Date = new Date()) {
  return { parts: item.parts, counted_at: item.countedAt, sent_at: sentAt.toISOString(), version: item.version };
}
