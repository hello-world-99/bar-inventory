import { useQuery } from "@tanstack/react-query";
import Big from "big.js";
import { useTranslation } from "react-i18next";
import { api } from "./api";
import type { AppSettings } from "./types";
import { formatQty, type Unit, type UnitInfo } from "./units";

export function useAppSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: () => api<AppSettings>("/settings"), staleTime: 5 * 60_000 });
}

export interface Currency {
  code: "KRW" | "USD";
  decimals: number;
  /** won per dollar when showing dollars, else null */
  rate: Big | null;
  /** an amount stored in won, in the display currency */
  toDisplay: (won: string | number) => Big;
  /** format an amount that is ALREADY in the display currency (e.g. a price being typed in) */
  format: (display: string | number | Big) => string;
}

/**
 * Money is stored in won; settings.currency is only how it is shown (and typed in). Dollars are won divided by
 * the current rate (replies 34-35). Conversion happens here and nowhere else.
 */
export function moneyFormat(s: Pick<AppSettings, "currency" | "currency_decimals" | "usd_krw_rate"> | undefined, lang: string): Currency {
  const usd = s?.currency === "USD" && !!s.usd_krw_rate;
  const code = usd ? "USD" : "KRW";
  const decimals = usd ? 2 : 0;
  const rate = usd ? new Big(s!.usd_krw_rate!) : null;
  const toDisplay = (won: string | number) => {
    const b = new Big(won || 0);
    return rate ? b.div(rate) : b;
  };
  let nf: Intl.NumberFormat | null = null;
  try {
    nf = new Intl.NumberFormat(lang, { style: "currency", currency: code, minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  } catch {
    nf = null;
  }
  const format = (v: string | number | Big) => {
    const n = Number(new Big(v || 0).round(decimals, Big.roundHalfUp).toString());
    return nf ? nf.format(n) : `${n.toFixed(decimals)} ${code}`;
  };
  return { code, decimals, rate, toDisplay, format };
}

export function useCurrency(): Currency {
  const { i18n } = useTranslation();
  return moneyFormat(useAppSettings().data, i18n.language);
}

/** Formats an amount stored in won in the display currency. */
export function useMoney() {
  const c = useCurrency();
  return (won: string | number) => c.format(c.toDisplay(won));
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
