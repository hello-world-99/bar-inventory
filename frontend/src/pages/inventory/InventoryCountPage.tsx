import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Big from "big.js";
import { ArrowLeft, CloudOff } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { ProductPicker, useActiveProducts } from "@/components/pickers";
import { Alert, Badge, Button, Card, cn, Input, PageHeader, Select } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { enqueue, isDefinite, loadQueue, settle, toRequest, type PendingCount } from "@/lib/countQueue";
import { uuidv4 } from "@/lib/uuid";
import { errorMessage } from "@/lib/errors";
import { useDateTime, useQty } from "@/lib/format";
import type { Inventory, InventoryLine, PendingDays, Product } from "@/lib/types";
import { CONTAINERS, inputUnits, plain, type Unit } from "@/lib/units";
import { DocumentView } from "../documents/DocumentView";
import { statusTone } from "./InventoryListPage";

const isNum = (s: string) => /^\d+(\.\d+)?$/.test(s.trim());
type Filter = "all" | "todo" | "diff";

/** Sends pending counts of this inventory; keeps them on network failure, drops them on a definite answer. */
function usePendingCounts(inventoryId: number, userId: number, onSent: () => void) {
  const { t } = useTranslation();
  const [pending, setPending] = useState<PendingCount[]>(() => loadQueue(userId, inventoryId));
  const [problems, setProblems] = useState<Record<number, string>>({});
  const busy = useRef(false);
  const again = useRef(false);
  // versions this device just produced, so an input made before the page refetched does not conflict with itself
  const sentVersion = useRef<Record<number, number>>({});

  // One upload at a time, in order; an input saved during a run triggers another run right after it.
  const flush = useCallback(async () => {
    if (busy.current) {
      again.current = true;
      return;
    }
    busy.current = true;
    try {
      do {
        again.current = false;
        for (const queued of loadQueue(userId, inventoryId)) {
          // re-read: an answer to the previous upload may have handed this entry a newer version
          const item = loadQueue(userId, inventoryId).find((x) => x.entryId === queued.entryId);
          if (!item) continue;
          try {
            const line = await api<InventoryLine>(`/inventories/${item.inventoryId}/lines/${item.productId}`, { method: "PUT", body: toRequest(item) });
            settle(item, line.version);
            sentVersion.current[item.productId] = line.version;
            setProblems((p) => ({ ...p, [item.productId]: "" }));
          } catch (err) {
            const definite = err instanceof ApiError && isDefinite(err.status);
            if (!definite) return; // offline, server restarting or signed out: keep the queue, retry later
            settle(item, null);
            setProblems((p) => ({
              ...p,
              [item.productId]: err instanceof ApiError && err.detail?.code === "version_conflict" ? t("inventory.conflict") : errorMessage(err, t),
            }));
          }
        }
      } while (again.current);
    } finally {
      busy.current = false;
      setPending(loadQueue(userId, inventoryId));
      onSent();
    }
  }, [inventoryId, userId, onSent, t]);

  useEffect(() => {
    void flush();
    const retry = () => void flush();
    window.addEventListener("online", retry);
    const timer = window.setInterval(retry, 15_000);
    return () => {
      window.removeEventListener("online", retry);
      window.clearInterval(timer);
    };
  }, [flush]);

  const save = (item: PendingCount) => {
    const own = sentVersion.current[item.productId];
    enqueue(own !== undefined && (item.version === null || own > item.version) ? { ...item, version: own } : item);
    setPending(loadQueue(userId, inventoryId));
    void flush();
  };
  return { pending, problems, save };
}

function CountInput({ line, onSave, disabled }: { line: Pick<InventoryLine, "unit" | "base_unit" | "unit_size" | "counted_base">; onSave: (parts: { qty: string; qty_unit: Unit }[]) => void; disabled?: boolean }) {
  const { t } = useTranslation();
  const inner = CONTAINERS[line.unit]; // bottles: full + open ml; packs: full + open g
  const isBottle = !!inner;
  const [full, setFull] = useState("");
  const [open, setOpen] = useState("");
  const [qty, setQty] = useState("");
  const [unit, setUnit] = useState<Unit>(line.unit);
  const units = inputUnits(line);

  function submit() {
    if (isBottle) {
      const f = full.trim() || "0";
      const o = open.trim() || "0";
      if (!isNum(f) || !isNum(o) || (full.trim() === "" && open.trim() === "")) return;
      onSave([{ qty: f, qty_unit: line.unit }, { qty: o, qty_unit: inner! }]);
      setFull("");
      setOpen("");
    } else {
      if (!isNum(qty)) return;
      onSave([{ qty, qty_unit: unit }]);
      setQty("");
    }
  }

  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      {isBottle ? (
        <>
          <label className="text-xs text-zinc-500">
            {t(line.unit === "pack" ? "inventory.fullPacks" : "inventory.fullBottles")}
            <Input inputMode="decimal" className="mt-1 w-24" value={full} onChange={(e) => setFull(e.target.value.replace(",", "."))} disabled={disabled} />
          </label>
          <span className="pb-2 text-zinc-400">+</span>
          <label className="text-xs text-zinc-500">
            {t(line.unit === "pack" ? "inventory.openG" : "inventory.openMl", { size: plain(new Big(line.unit_size)) })}
            <Input inputMode="decimal" className="mt-1 w-28" value={open} onChange={(e) => setOpen(e.target.value.replace(",", "."))} disabled={disabled} />
          </label>
        </>
      ) : (
        <label className="text-xs text-zinc-500">
          {t("inventory.counted")}
          <div className="mt-1 flex gap-2">
            <Input inputMode="decimal" className="w-28" value={qty} onChange={(e) => setQty(e.target.value.replace(",", "."))} disabled={disabled} />
            {units.length > 1 && (
              <Select className="w-20" value={unit} onChange={(e) => setUnit(e.target.value as Unit)} disabled={disabled}>
                {units.map((u) => (
                  <option key={u} value={u}>
                    {t(`units.short.${u}`)}
                  </option>
                ))}
              </Select>
            )}
            {units.length === 1 && <span className="self-center text-sm text-zinc-500">{t(`units.short.${line.unit}`)}</span>}
          </div>
        </label>
      )}
      <Button type="submit" disabled={disabled}>
        {line.counted_base === null ? t("common.save") : t("inventory.recount")}
      </Button>
    </form>
  );
}

function LineCard({ line, editable, pending, problem, onSave, onClear }: {
  line: InventoryLine; editable: boolean; pending?: PendingCount; problem?: string;
  onSave: (parts: { qty: string; qty_unit: Unit }[]) => void; onClear: () => void;
}) {
  const { t } = useTranslation();
  const qty = useQty();
  const dt = useDateTime();
  const counted = line.counted_base !== null;
  const diff = line.diff_base !== null ? new Big(line.diff_base) : null;
  return (
    <Card className={cn("p-4 sm:p-4", counted && "border-emerald-200 bg-emerald-50/30", !line.product_active && "opacity-60")}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-medium">{line.product_name}</div>
          <div className="text-xs text-zinc-500">{line.product_sku}</div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {line.expected_base !== null && (
            <span className="text-zinc-500">
              {t("inventory.expected")}: <span className="font-medium text-zinc-800">{qty(line.expected_base, line).main}</span>
            </span>
          )}
          {counted && (
            <span>
              {t("inventory.counted")}: <span className="font-semibold">{qty(line.counted_base!, line).main}</span>
            </span>
          )}
          {diff && !diff.eq(0) && (
            <Badge tone={diff.lt(0) ? "red" : "green"}>
              {diff.gt(0) ? "+" : ""}
              {qty(line.diff_base!, line).main}
            </Badge>
          )}
          {diff && diff.eq(0) && <Badge tone="green">{t("inventory.match")}</Badge>}
          {pending && (
            <Badge tone="amber">
              <CloudOff className="mr-1 h-3 w-3" />
              {t("inventory.pending")}
            </Badge>
          )}
        </div>
      </div>
      {counted && line.counted_at && (
        <p className="mt-1 text-xs text-zinc-500">
          {t("inventory.countedBy", { who: line.counted_by_name, when: dt(line.counted_at) })}
          {editable && (
            <button type="button" className="ml-2 underline hover:text-zinc-800" onClick={onClear}>
              {t("inventory.clear")}
            </button>
          )}
        </p>
      )}
      {problem && (
        <div className="mt-2">
          <Alert>{problem}</Alert>
        </div>
      )}
      {editable && line.product_active && (
        <div className="mt-3">
          <CountInput line={line} onSave={onSave} />
        </div>
      )}
    </Card>
  );
}

function CompleteDialog({ inv, onClose }: { inv: Inventory; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [zero, setZero] = useState(false);
  const done = useMutation({
    mutationFn: () => api<Inventory>(`/inventories/${inv.id}/complete`, { method: "POST", body: { zero_uncounted: zero } }),
    onSuccess: (r) => {
      qc.setQueryData(["inventory", inv.id], r);
      void qc.invalidateQueries();
      onClose();
    },
  });
  const uncounted = inv.line_count - inv.counted_count;
  // Sales of days without a POS write-off are still in the expected quantity: they would read as a shortage (reply 32, P3).
  const pendingSales = useQuery({
    queryKey: ["sales-pending", inv.location_id],
    queryFn: () => api<PendingDays>(`/sales-imports/pending-days?location_id=${inv.location_id}`),
  }).data;
  return (
    <Modal title={t("inventory.completeTitle", { name: inv.location_name })} onClose={onClose}>
      <div className="space-y-4 text-sm">
        {done.error && <Alert>{errorMessage(done.error, t)}</Alert>}
        <p>{t("inventory.completeExplain")}</p>
        {pendingSales && pendingSales.days.length > 0 && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-900">
            <p className="font-medium">{t("inventory.pendingSalesTitle")}</p>
            <p>
              {t("inventory.pendingSales", { days: pendingSales.days.join(", ") })}
              {pendingSales.more > 0 && t("inventory.pendingSalesMore", { count: pendingSales.more })}
            </p>
          </div>
        )}
        {uncounted > 0 && (
          <label className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3">
            <input type="checkbox" className="mt-0.5 h-4 w-4" checked={zero} onChange={(e) => setZero(e.target.checked)} />
            <span>
              {t("inventory.zeroUncounted", { count: uncounted })}
              <span className="block text-xs text-zinc-600">{t("inventory.zeroUncountedHint")}</span>
            </span>
          </label>
        )}
        <div className="flex gap-2">
          <Button disabled={done.isPending} onClick={() => done.mutate()}>
            {t("inventory.confirmComplete")}
          </Button>
          <Button variant="secondary" onClick={onClose}>
            {t("common.cancel")}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

export function InventoryCountPage() {
  const { id } = useParams();
  const invId = Number(id);
  const { t } = useTranslation();
  const { can, user } = useAuth();
  const qc = useQueryClient();
  const dt = useDateTime();
  const products = useActiveProducts().data ?? [];
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [extra, setExtra] = useState<Product | null>(null);
  const [completing, setCompleting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [openDoc, setOpenDoc] = useState<string | null>(null);

  const q = useQuery({
    queryKey: ["inventory", invId],
    queryFn: () => api<Inventory>(`/inventories/${invId}`),
    refetchInterval: (query) => (query.state.data?.status === "in_progress" ? 20_000 : false), // see colleagues' counts
  });
  const refresh = useCallback(() => void qc.invalidateQueries({ queryKey: ["inventory", invId] }), [qc, invId]);
  const { pending, problems, save } = usePendingCounts(invId, user?.id ?? 0, refresh);
  const cancel = useMutation({
    mutationFn: () => api<Inventory>(`/inventories/${invId}/cancel`, { method: "POST" }),
    onSuccess: () => {
      setCancelling(false);
      void qc.invalidateQueries();
    },
  });
  const clear = useMutation({
    mutationFn: (l: InventoryLine) => api(`/inventories/${invId}/lines/${l.product_id}/count?version=${l.version}`, { method: "DELETE" }),
    onSettled: refresh,
  });

  const inv = q.data;
  const editable = inv?.status === "in_progress" && can("inventory_count");
  const lines = useMemo(() => {
    const s = search.trim().toLowerCase();
    return (inv?.lines ?? []).filter((l) => {
      if (s && !l.product_name.toLowerCase().includes(s) && !l.product_sku.toLowerCase().includes(s)) return false;
      if (filter === "todo") return l.counted_base === null;
      if (filter === "diff") return l.diff_base !== null && !new Big(l.diff_base).eq(0);
      return true;
    });
  }, [inv, search, filter]);

  if (!inv) return <PageHeader title={q.error ? errorMessage(q.error, t) : t("common.loading")} />;

  const saveLine = (productId: number, version: number | null) => (parts: { qty: string; qty_unit: Unit }[]) =>
    save({ key: `${invId}:${productId}`, entryId: uuidv4(), userId: user?.id ?? 0, inventoryId: invId, productId, parts, countedAt: new Date().toISOString(), version });
  const extraLine: InventoryLine | null =
    extra && !inv.lines.some((l) => l.product_id === extra.id)
      ? { product_id: extra.id, product_name: extra.name, product_sku: extra.sku, category_code: extra.category_code, category_name: extra.category_name, unit: extra.unit, base_unit: extra.base_unit, unit_size: extra.unit_size, product_active: true, counted_base: null, counted_at: null, counted_by_name: null, version: 0, expected_at_start_base: null, expected_base: null, diff_base: null, unit_cost_base: null, diff_cost: null }
      : null;

  return (
    <>
      <Link to="/inventory" className="mb-3 inline-flex items-center gap-1 text-sm text-zinc-600 hover:text-zinc-900">
        <ArrowLeft className="h-4 w-4" /> {t("nav.inventory")}
      </Link>
      <PageHeader
        title={`${inv.location_name} · #${inv.id}`}
        actions={
          inv.status === "in_progress" &&
          can("inventory_review") && (
            <>
              <Button onClick={() => setCompleting(true)} disabled={pending.length > 0}>
                {t("inventory.complete")}
              </Button>
              <Button variant="secondary" onClick={() => setCancelling(true)}>
                {t("inventory.cancel")}
              </Button>
            </>
          )
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm text-zinc-600">
        <Badge tone={statusTone(inv.status)}>{t(`inventory.status.${inv.status}`)}</Badge>
        <span>{t("inventory.progress", { counted: inv.counted_count, total: inv.line_count })}</span>
        <span>· {t("inventory.startedBy", { who: inv.started_by_name, when: dt(inv.started_at) })}</span>
        {inv.blind && <Badge>{t("inventory.blind")}</Badge>}
        {pending.length > 0 && <Badge tone="amber">{t("inventory.pendingCount", { count: pending.length })}</Badge>}
      </div>
      {inv.status === "in_progress" && pending.length > 0 && can("inventory_review") && <p className="mb-3 text-xs text-amber-700">{t("inventory.syncBeforeComplete")}</p>}

      {inv.status !== "in_progress" && inv.adjustment_document_id && (
        <Card className="mb-4">
          {inv.adjustment_document_id && (
            <Button variant="secondary" className="mt-3" onClick={() => setOpenDoc(inv.adjustment_document_id)}>
              {t("inventory.openAdjustment")}
            </Button>
          )}
        </Card>
      )}

      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Input type="search" placeholder={t("common.search")} value={search} onChange={(e) => setSearch(e.target.value)} />
        <Select value={filter} onChange={(e) => setFilter(e.target.value as Filter)}>
          <option value="all">{t("inventory.filter.all")}</option>
          <option value="todo">{t("inventory.filter.todo")}</option>
          {!inv.blind && <option value="diff">{t("inventory.filter.diff")}</option>}
        </Select>
        {editable && (
          <ProductPicker products={products.filter((p) => !inv.lines.some((l) => l.product_id === p.id))} value={extra?.id ?? null} onChange={setExtra} />
        )}
      </div>
      {editable && <p className="-mt-2 mb-4 text-xs text-zinc-500">{t("inventory.addHint")}</p>}

      <div className="space-y-3">
        {extraLine && (
          <LineCard line={extraLine} editable pending={pending.find((p) => p.productId === extraLine.product_id)} problem={problems[extraLine.product_id]} onSave={saveLine(extraLine.product_id, 0)} onClear={() => undefined} />
        )}
        {lines.map((l) => (
          <LineCard
            key={l.product_id}
            line={l}
            editable={editable}
            pending={pending.find((p) => p.productId === l.product_id)}
            problem={problems[l.product_id]}
            onSave={saveLine(l.product_id, l.version)}
            onClear={() => clear.mutate(l)}
          />
        ))}
        {lines.length === 0 && !extraLine && <p className="py-8 text-center text-sm text-zinc-500">{t("common.noResults")}</p>}
      </div>

      {completing && <CompleteDialog inv={inv} onClose={() => setCompleting(false)} />}
      {cancelling && (
        <Modal title={t("inventory.cancelTitle")} onClose={() => setCancelling(false)}>
          <p className="text-sm">{t("inventory.cancelExplain")}</p>
          {cancel.error && <Alert>{errorMessage(cancel.error, t)}</Alert>}
          <div className="mt-4 flex gap-2">
            <Button variant="danger" disabled={cancel.isPending} onClick={() => cancel.mutate()}>
              {t("inventory.cancel")}
            </Button>
            <Button variant="secondary" onClick={() => setCancelling(false)}>
              {t("common.cancel")}
            </Button>
          </div>
        </Modal>
      )}
      {openDoc && <DocumentView id={openDoc} onClose={() => setOpenDoc(null)} />}
    </>
  );
}
