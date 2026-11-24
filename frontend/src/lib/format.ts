import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api } from "./api";
import type { AppSettings } from "./types";
import { formatQty, type Unit, type UnitInfo } from "./units";

export function useAppSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: () => api<AppSettings>("/settings"), staleTime: 5 * 60_000 });
}

export function useMoney() {
  const { i18n } = useTranslation();
  const s = useAppSettings().data;
  return (value: string | number) => {
    const n = typeof value === "string" ? Number(value) : value;
    if (!s) return n.toFixed(2);
    try {
      return new Intl.NumberFormat(i18n.language, {
        style: "currency",
        currency: s.currency,
        minimumFractionDigits: s.currency_decimals,
        maximumFractionDigits: s.currency_decimals,
      }).format(n);
    } catch {
      return `${n.toFixed(s.currency_decimals)} ${s.currency}`;
    }
  };
}

export function useQty() {
  const { t } = useTranslation();
  const label = (u: Unit) => t(`units.short.${u}`);
  return (qtyBase: string, p: UnitInfo) => formatQty(qtyBase, p, label);
}

/** Date-time in the installation's time zone (settings.timezone), formatted for the UI language. */
export function useDateTime() {
  const { i18n } = useTranslation();
  const s = useAppSettings().data;
  return (iso: string, opts: Intl.DateTimeFormatOptions = { dateStyle: "medium", timeStyle: "short" }) => {
    try {
      return new Intl.DateTimeFormat(i18n.language, { ...opts, timeZone: s?.timezone }).format(new Date(iso));
    } catch {
      return new Date(iso).toLocaleString();
    }
  };
}
