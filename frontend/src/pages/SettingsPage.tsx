import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Big from "big.js";
import { RefreshCw } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, Card, Field, Input, PageHeader, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useDateTime } from "@/lib/format";
import type { AppSettings } from "@/lib/types";

const TIMEZONES: string[] =
  typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : ["UTC", "Asia/Seoul", "Europe/Moscow"];

const isRate = (s: string) => /^\d+(\.\d{1,4})?$/.test(s.trim()) && Number(s) >= 100 && Number(s) <= 100000;

/** Exchange rate block: automatic (daily fetch, "Update now") or typed in (replies 34-35). */
function RateBlock({ s, mode, setMode, manual, setManual }: {
  s: AppSettings; mode: AppSettings["rate_mode"]; setMode: (m: AppSettings["rate_mode"]) => void; manual: string; setManual: (v: string) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const dt = useDateTime();
  const now = useMutation({
    mutationFn: () => api<AppSettings>("/settings/rate/update", { method: "POST" }),
    onSuccess: (data) => qc.setQueryData(["settings"], data),
  });
  const rate = s.usd_krw_rate ? new Big(s.usd_krw_rate).toFixed(2) : null;
  return (
    <div className="space-y-3 rounded-lg border border-zinc-200 p-3 sm:col-span-2">
      <div className="text-sm font-medium text-zinc-700">{t("settings.rate")}</div>
      <div className="flex flex-wrap gap-4 text-sm">
        {(["auto", "manual"] as const).map((m) => (
          <label key={m} className="flex items-center gap-2">
            <input type="radio" name="rate_mode" className="h-4 w-4" checked={mode === m} onChange={() => setMode(m)} />
            {t(`settings.rateMode.${m}`)}
          </label>
        ))}
      </div>
      {mode === "manual" ? (
        <Field label={t("settings.manualRate")} error={manual && !isRate(manual) ? t("settings.rateInvalid") : undefined}>
          <Input inputMode="decimal" value={manual} placeholder="1400" onChange={(e) => setManual(e.target.value.replace(",", "."))} />
        </Field>
      ) : (
        <div className="space-y-2 text-sm">
          {rate ? (
            <p>
              <span className="font-semibold">{t("settings.rateValue", { rate })}</span>{" "}
              <span className="text-zinc-500">
                {t("settings.rateFrom", { source: s.rate_source ?? "", date: s.rate_date ?? (s.rate_updated_at ? dt(s.rate_updated_at) : "") })}
              </span>
            </p>
          ) : (
            <p className="text-zinc-500">{t("settings.noRate")}</p>
          )}
          {s.rate_error && (
            <p className="text-amber-700">
              {t("settings.rateFailed", { when: s.rate_checked_at ? dt(s.rate_checked_at) : "", error: s.rate_error })}
            </p>
          )}
          {s.rate_mode === "auto" && (
            <Button type="button" variant="secondary" disabled={now.isPending} onClick={() => now.mutate()}>
              <RefreshCw className="h-4 w-4" /> {t("settings.updateNow")}
            </Button>
          )}
          {now.error && <Alert>{errorMessage(now.error, t)}</Alert>}
        </div>
      )}
      <p className="text-xs text-zinc-500">{t("settings.rateHint")}</p>
    </div>
  );
}

export function SettingsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["settings"], queryFn: () => api<AppSettings>("/settings") });
  const [d, setD] = useState<AppSettings | null>(null);
  const [manual, setManual] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (q.data) {
      setD({ ...q.data, business_day_starts_at: q.data.business_day_starts_at.slice(0, 5) });
      setManual(q.data.rate_mode === "manual" && q.data.usd_krw_rate ? new Big(q.data.usd_krw_rate).toString() : "");
    }
  }, [q.data]);

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api<AppSettings>("/settings", { method: "PATCH", body }),
    onSuccess: (data) => {
      qc.setQueryData(["settings"], data);
      void qc.invalidateQueries();
      setSaved(true);
    },
  });

  if (!d || !q.data) return <PageHeader title={t("settings.title")} />;
  const hasRate = d.rate_mode === "manual" ? isRate(manual) : !!q.data.usd_krw_rate;

  function submit(e: FormEvent) {
    e.preventDefault();
    setSaved(false);
    if (!d) return;
    const body: Record<string, unknown> = {
      venue_name: d.venue_name, currency: d.currency, timezone: d.timezone, business_day_starts_at: d.business_day_starts_at,
      blind_count: d.blind_count, rate_mode: d.rate_mode,
    };
    if (d.rate_mode === "manual" && isRate(manual)) body.usd_krw_rate = manual.trim();
    save.mutate(body);
  }

  const tzs = TIMEZONES.includes(d.timezone) ? TIMEZONES : [d.timezone, ...TIMEZONES];

  return (
    <>
      <PageHeader title={t("settings.title")} />
      <Card className="max-w-2xl">
        <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
          {save.error && (
            <div className="sm:col-span-2">
              <Alert>{errorMessage(save.error, t)}</Alert>
            </div>
          )}
          {saved && (
            <div className="sm:col-span-2">
              <Alert tone="green">{t("common.saved")}</Alert>
            </div>
          )}
          <div className="sm:col-span-2">
            <Field label={t("settings.venueName")}>
              <Input value={d.venue_name} onChange={(e) => setD({ ...d, venue_name: e.target.value })} required />
            </Field>
          </div>
          <Field label={t("settings.currency")} hint={d.currency === "USD" && !hasRate ? t("settings.usdNeedsRate") : undefined}>
            <Select value={d.currency} onChange={(e) => setD({ ...d, currency: e.target.value as AppSettings["currency"] })}>
              <option value="KRW">{t("settings.currencies.KRW")}</option>
              <option value="USD" disabled={!hasRate}>
                {t("settings.currencies.USD")}
              </option>
            </Select>
          </Field>
          <div className="hidden sm:block" />
          <RateBlock s={q.data} mode={d.rate_mode} setMode={(m) => setD({ ...d, rate_mode: m })} manual={manual} setManual={setManual} />
          <Field label={t("settings.timezone")}>
            <Select value={d.timezone} onChange={(e) => setD({ ...d, timezone: e.target.value })}>
              {tzs.map((z) => (
                <option key={z} value={z}>
                  {z}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t("settings.businessDayStart")} hint={t("settings.businessDayHint")}>
            <Input type="time" value={d.business_day_starts_at} onChange={(e) => setD({ ...d, business_day_starts_at: e.target.value })} required />
          </Field>
          <label className="flex items-start gap-3 sm:col-span-2">
            <input type="checkbox" className="mt-1 h-4 w-4" checked={d.blind_count} onChange={(e) => setD({ ...d, blind_count: e.target.checked })} />
            <span>
              <span className="block text-sm font-medium text-zinc-700">{t("settings.blindCount")}</span>
              <span className="block text-xs text-zinc-500">{t("settings.blindCountHint")}</span>
            </span>
          </label>
          <div className="sm:col-span-2">
            <Button type="submit" disabled={save.isPending || (d.currency === "USD" && !hasRate)}>
              {t("common.save")}
            </Button>
          </div>
        </form>
      </Card>
    </>
  );
}
