import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { LocationSelect, useActiveLocations } from "@/components/pickers";
import { Alert, Badge, Button, Card, Field, Input, PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useDateTime, useMoney } from "@/lib/format";
import type { Inventory } from "@/lib/types";

export function statusTone(s: Inventory["status"]) {
  return s === "in_progress" ? "amber" : s === "completed" ? "green" : "neutral";
}

export function InventoryListPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const nav = useNavigate();
  const qc = useQueryClient();
  const money = useMoney();
  const dt = useDateTime();
  const locations = useActiveLocations().data ?? [];
  const [starting, setStarting] = useState(false);
  const [location, setLocation] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const list = useQuery({ queryKey: ["inventories"], queryFn: () => api<Inventory[]>("/inventories?limit=100") });

  const start = useMutation({
    mutationFn: () => api<Inventory>("/inventories", { method: "POST", body: { location_id: location, comment } }),
    onSuccess: (inv) => {
      void qc.invalidateQueries({ queryKey: ["inventories"] });
      void qc.invalidateQueries({ queryKey: ["locations"] });
      nav(`/inventory/${inv.id}`);
    },
  });
  const running = (list.data ?? []).find((i) => i.status === "in_progress" && i.location_id === location);

  return (
    <>
      <PageHeader title={t("nav.inventory")} actions={can("inventory_count") && <Button onClick={() => setStarting(true)}>{t("inventory.start")}</Button>} />
      {list.error && <Alert>{errorMessage(list.error, t)}</Alert>}
      {list.data?.length === 0 && (
        <Card>
          <p className="text-sm text-zinc-500">{t("inventory.empty")}</p>
        </Card>
      )}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {list.data?.map((inv) => (
          <button key={inv.id} type="button" onClick={() => nav(`/inventory/${inv.id}`)} className="text-left">
            <Card className="h-full transition-colors hover:border-zinc-400">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h2 className="font-semibold">{inv.location_name}</h2>
                  <p className="text-xs text-zinc-500">
                    #{inv.id} · {dt(inv.started_at)} · {inv.started_by_name}
                  </p>
                </div>
                <Badge tone={statusTone(inv.status)}>{t(`inventory.status.${inv.status}`)}</Badge>
              </div>
              <p className="mt-3 text-sm text-zinc-600">{t("inventory.progress", { counted: inv.counted_count, total: inv.line_count })}</p>
              {inv.status === "completed" && inv.net_cost !== null && (
                <p className="mt-1 text-sm">
                  {t("inventory.net")}: <span className={Number(inv.net_cost) < 0 ? "font-semibold text-red-700" : "font-semibold text-emerald-700"}>{money(inv.net_cost)}</span>
                </p>
              )}
              {inv.closed_at && inv.status !== "in_progress" && (
                <p className="mt-1 text-xs text-zinc-500">
                  {t(`inventory.closedBy.${inv.status}`, { when: dt(inv.closed_at), who: inv.closed_by_name })}
                </p>
              )}
            </Card>
          </button>
        ))}
      </div>
      {starting && (
        <Modal title={t("inventory.start")} onClose={() => setStarting(false)}>
          <div className="space-y-4">
            {start.error && !(start.error instanceof ApiError && start.error.status === 409) && <Alert>{errorMessage(start.error, t)}</Alert>}
            <Field label={t("docs.location")}>
              <LocationSelect locations={locations} value={location} onChange={setLocation} />
            </Field>
            <Field label={t("docs.comment")}>
              <Input value={comment} onChange={(e) => setComment(e.target.value)} maxLength={1000} />
            </Field>
            {running || (start.error instanceof ApiError && start.error.status === 409) ? (
              <div className="space-y-2">
                <Alert>{t("inventory.alreadyRunning")}</Alert>
                {running && <Button onClick={() => nav(`/inventory/${running.id}`)}>{t("inventory.openRunning")}</Button>}
              </div>
            ) : (
              <p className="text-sm text-zinc-600">{t("inventory.startHint")}</p>
            )}
            <div className="flex gap-2">
              <Button disabled={!location || start.isPending || !!running} onClick={() => start.mutate()}>
                {t("inventory.start")}
              </Button>
              <Button variant="secondary" onClick={() => setStarting(false)}>
                {t("common.cancel")}
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}
