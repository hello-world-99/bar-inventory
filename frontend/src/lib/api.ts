export interface ErrorDetail {
  code?: string;
  message?: string;
  can_override?: boolean;
  items?: { product_id: number; location_id: number; available: string; requested: string }[];
  [k: string]: unknown;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body?: unknown,
  ) {
    super(message);
  }

  /** Structured `detail` of business-rule errors (e.g. {code: "insufficient_stock", can_override: true}). */
  get detail(): ErrorDetail | undefined {
    const d = (this.body as { detail?: unknown } | undefined)?.detail;
    return d && typeof d === "object" && !Array.isArray(d) ? (d as ErrorDetail) : undefined;
  }
}

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
let onSessionExpired: () => void = () => {};

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function setSessionExpiredHandler(fn: () => void) {
  onSessionExpired = fn;
}

function detailMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (d && typeof d === "object" && "message" in d && typeof (d as { message: unknown }).message === "string") {
      return (d as { message: string }).message;
    }
    if (Array.isArray(d) && d.length && typeof d[0]?.msg === "string") {
      return d.map((e: { msg: string; loc?: unknown[] }) => `${(e.loc ?? []).slice(1).join(".")}: ${e.msg}`).join("; ");
    }
  }
  return fallback;
}

/** Exchange the httpOnly refresh cookie for a new access token. Concurrent callers share one request. */
export function refreshSession(): Promise<boolean> {
  refreshing ??= fetch("/api/v1/auth/refresh", { method: "POST", credentials: "same-origin" })
    .then(async (r) => {
      if (!r.ok) return false;
      setAccessToken((await r.json()).access_token);
      return true;
    })
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

export interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  /** internal: do not attempt token refresh on 401 */
  noRetry?: boolean;
}

export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { body, noRetry, headers, ...rest } = opts;
  const h = new Headers(headers);
  // A Blob (e.g. an uploaded .xlsx) is sent as is; the caller sets its Content-Type. Anything else is JSON.
  const raw = body instanceof Blob;
  if (body !== undefined && !raw) h.set("Content-Type", "application/json");
  if (accessToken) h.set("Authorization", `Bearer ${accessToken}`);

  const res = await fetch(`/api/v1${path}`, {
    ...rest,
    headers: h,
    credentials: "same-origin",
    body: body === undefined ? undefined : raw ? body : JSON.stringify(body),
  });

  if (res.status === 401 && !noRetry && !path.startsWith("/auth/login")) {
    if (await refreshSession()) return api<T>(path, { ...opts, noRetry: true });
    setAccessToken(null);
    onSessionExpired();
  }
  if (res.status === 204) return undefined as T;

  const text = await res.text();
  let data: unknown;
  let parsed = true;
  try {
    data = text ? JSON.parse(text) : undefined;
  } catch {
    // e.g. nginx HTML error page while the backend restarts
    data = undefined;
    parsed = false;
  }
  if (!res.ok) throw new ApiError(res.status, detailMessage(data, res.statusText || `HTTP ${res.status}`), data);
  if (!parsed) throw new ApiError(res.status, "Unexpected response from server");
  return data as T;
}
