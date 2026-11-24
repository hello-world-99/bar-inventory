import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { Alert, Badge, Button, Card, Field, Input, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Location } from "@/lib/types";

function LocationForm({ loc, onDone }: { loc?: Location; onDone: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [name, setName] = useState(loc?.name ?? "");
  const [description, setDescription] = useState(loc?.description ?? "");
  const save = useMutation({
    mutationFn: () =>
      loc
        ? api<Location>(`/locations/${loc.id}`, { method: "PATCH", body: { name, description } })
        : api<Location>("/locations", { method: "POST", body: { name, description } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["locations"] });
      onDone();
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate();
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      {save.error && <Alert>{errorMessage(save.error, t)}</Alert>}
      <Field label={t("locations.name")}>
        <Input value={name} onChange={(e) => setName(e.target.value)} required maxLength={64} autoFocus placeholder={t("locations.namePlaceholder")} />
      </Field>
      <Field label={t("locations.description")}>
        <Input value={description} onChange={(e) => setDescription(e.target.value)} maxLength={255} />
      </Field>
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending}>
          {loc ? t("common.save") : t("common.create")}
        </Button>
        <Button variant="secondary" onClick={onDone}>
          {t("common.cancel")}
        </Button>
      </div>
    </form>
  );
}

export function LocationsPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const manage = can("manage_catalog");
  const [showInactive, setShowInactive] = useState(false);
  const [editing, setEditing] = useState<Location | "new" | null>(null);
  const [confirm, setConfirm] = useState<Location | null>(null);
  const locs = useQuery({
    queryKey: ["locations", showInactive ? "all" : "active"],
    queryFn: () => api<Location[]>(`/locations?active=${showInactive ? "all" : "active"}`),
  });
  const toggle = useMutation({
    mutationFn: (l: Location) => api<Location>(`/locations/${l.id}`, { method: "PATCH", body: { is_active: !l.is_active } }),
    onSuccess: () => {
      setConfirm(null);
      void qc.invalidateQueries({ queryKey: ["locations"] });
    },
  });

  return (
    <>
      <PageHeader title={t("nav.locations")} actions={manage && <Button onClick={() => setEditing("new")}>{t("locations.new")}</Button>} />
      <label className="mb-4 flex items-center gap-2 text-sm">
        <input type="checkbox" className="h-4 w-4" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
        {t("locations.showInactive")}
      </label>
      {toggle.error && (
        <div className="mb-4">
          <Alert>{errorMessage(toggle.error, t)}</Alert>
        </div>
      )}
      {locs.isLoading && <p className="text-sm text-zinc-500">{t("common.loading")}</p>}
      {locs.data?.length === 0 && (
        <Card>
          <p className="text-sm text-zinc-500">{t("locations.empty")}</p>
        </Card>
      )}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {locs.data?.map((l) => (
          <Card key={l.id} className={l.is_active ? "" : "opacity-60"}>
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <h2 className="truncate font-semibold">{l.name}</h2>
                {l.description && <p className="mt-0.5 text-sm text-zinc-500">{l.description}</p>}
              </div>
              <div className="flex shrink-0 flex-col items-end gap-1">
                {!l.is_active && <Badge>{t("common.inactive")}</Badge>}
                {l.has_active_inventory && <Badge tone="amber">{t("locations.counting")}</Badge>}
              </div>
            </div>
            <p className="mt-3 text-sm text-zinc-600">{t("locations.productCount", { count: l.product_count })}</p>
            {manage && (
              <div className="mt-4 flex gap-2">
                <Button variant="secondary" onClick={() => setEditing(l)}>
                  {t("common.edit")}
                </Button>
                <Button variant="ghost" disabled={toggle.isPending} onClick={() => (l.is_active && l.product_count > 0 ? setConfirm(l) : toggle.mutate(l))}>
                  {l.is_active ? t("common.deactivate") : t("common.activate")}
                </Button>
              </div>
            )}
          </Card>
        ))}
      </div>
      {editing && (
        <Modal title={editing === "new" ? t("locations.new") : t("locations.edit")} onClose={() => setEditing(null)}>
          <LocationForm loc={editing === "new" ? undefined : editing} onDone={() => setEditing(null)} />
        </Modal>
      )}
      {confirm && (
        <Modal title={t("locations.deactivateTitle", { name: confirm.name })} onClose={() => setConfirm(null)}>
          <p className="text-sm text-zinc-700">{t("locations.deactivateWarning", { count: confirm.product_count })}</p>
          <div className="mt-5 flex gap-2">
            <Button variant="danger" disabled={toggle.isPending} onClick={() => toggle.mutate(confirm)}>
              {t("common.deactivate")}
            </Button>
            <Button variant="secondary" onClick={() => setConfirm(null)}>
              {t("common.cancel")}
            </Button>
          </div>
        </Modal>
      )}
    </>
  );
}
