import type { TFunction } from "i18next";
import { ApiError } from "./api";

/** User-facing message for any error thrown by api(). */
export function errorMessage(err: unknown, t: TFunction): string {
  if (err instanceof ApiError) {
    if (err.status === 502 || err.status === 503 || err.status === 504) return t("common.serverRestarting");
    if (err.status === 429) return t("auth.tooMany");
    return err.message;
  }
  if (err instanceof TypeError) return t("common.networkError"); // fetch failed: offline / unreachable
  return t("common.error");
}
