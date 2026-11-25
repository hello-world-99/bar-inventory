import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, Card, Field, Input, PageHeader, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { AppSettings } from "@/lib/types";

const TIMEZONES: string[] =
  typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : ["UTC", "Asia/Seoul", "Europe/Moscow"];

export function SettingsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["settings"], queryFn: () => api<AppSettings>("/settings") });
  const [d, setD] = useState<AppSettings | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (q.data) {
      setD({ ...q.data, business_day_starts_at: q.data.business_day_starts_at.slice(0, 5) });
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

  function submit(e: FormEvent) {
    e.preventDefault();
    setSaved(false);
    if (!d) return;
    const body: Record<string, unknown> = {
      venue_name: d.venue_name, timezone: d.timezone, business_day_starts_at: d.business_day_starts_at, blind_count: d.blind_count,
    };
    // currency and exchange rate are hidden for now (owner, reply 69); the API still has them
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
            <Button type="submit" disabled={save.isPending}>
              {t("common.save")}
            </Button>
          </div>
        </form>
      </Card>
    </>
  );
}
