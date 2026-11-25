import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Big from "big.js";
import { ArrowLeft } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { LocationSelect, useActiveLocations } from "@/components/pickers";
import { Alert, Badge, Button, Card, cn, Field, Input } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useCurrency, useDateTime, useMoney, useQty, type Currency } from "@/lib/format";
import type { PosLine, SalesImport, SalesImportStatus, SalesWarning, UsageItem } from "@/lib/types";
import { baseUnitInfo, plain } from "@/lib/units";
import { uuidv4 } from "@/lib/uuid";
import { DocumentView } from "../documents/DocumentView";
import { NormDialog } from "./NormDialog";

const LOCATION_KEY = "bar-inventory.sales-location";

function rememberedLocation(): number | null {
  try {
    const v = localStorage.getItem(LOCATION_KEY);
    return v ? Number(v) : null;
  } catch {
    return null;
  }
}

function remember(id: number) {
  try {
    localStorage.setItem(LOCATION_KEY, String(id));
  } catch {
    // private mode: just not remembered
  }
}

export function StatusBadge({ status }: { status: SalesImportStatus }) {
  const { t } = useTranslation();
  const tone = status === "posted" ? "green" : status === "covered" ? "amber" : status === "voided" ? "red" : "neutral";
  return <Badge tone={tone}>{t(`sales.statuses.${status}`)}</Badge>;
}

function Warning({ w }: { w: SalesWarning }) {
  const { t } = useTranslation();
  return <li>{t(`sales.warnings.${w.code}`, { ...w, defaultValue: w.code })}</li>;
}

/** A product's usage as typed in the draft report: quantity in the base unit, price per product unit (display currency). */
interface UsageEdit {
  qty: string;
  price: string;
}

const isDec = (v: string) => /^\d+(\.\d+)?$/.test(v.trim());

/** Effective quantity (base units) and amount (display currency) of a row, recalculated as the user types. */
function rowValues(item: UsageItem, e: UsageEdit | undefined, cur: Currency) {
  const qtyBase = e && isDec(e.qty) ? new Big(e.qty) : new Big(item.qty_base);
  const price = e && isDec(e.price) ? new Big(e.price) : cur.toDisplay(new Big(item.unit_cost_base).times(item.unit_size).toString());
  const amount = qtyBase.div(item.unit_size).times(price);
  const valid = !e || (isDec(e.qty) && isDec(e.price));
  return { qtyBase, price, amount, valid };
}

function UsageRow({ item, draft, editable, edit, onEdit }: {
  item: UsageItem; draft: boolean; editable: boolean; edit: UsageEdit | undefined; onEdit: (e: UsageEdit) => void;
}) {
  const { t } = useTranslation();
  const qty = useQty();
  const cur = useCurrency();
  const money = useMoney();
  const dt = useDateTime();
  const covered = item.covered_inventory_id !== null;
  const v = rowValues(item, edit, cur);
  const after = item.balance_base !== null ? new Big(item.balance_base).minus(v.qtyBase) : null;
  const low = after !== null && !covered && (after.lt(0) || (new Big(item.min_stock_base).gt(0) && after.lte(item.min_stock_base)));
  const perUnit = (base: string) => qty(base, baseUnitInfo(item)).main;
  const current = edit ?? { qty: plain(new Big(item.qty_base)), price: plain(v.price, cur.decimals) };
  return (
    <tr className={cn("border-t border-zinc-100 align-top", low && "bg-red-50")}>
      <td className="py-2 pr-3">
        <div className="font-medium">
          {item.product_name} {!item.is_active && <Badge tone="red">{t("common.inactive")}</Badge>}
        </div>
        {covered && (
          <div className="mt-1">
            <Badge tone="amber">
              {t(draft ? "sales.willBeSkipped" : "sales.countedBy", { id: String(item.covered_inventory_id), at: item.covered_at ? dt(item.covered_at) : "" })}
            </Badge>
          </div>
        )}
        <ul className="mt-1 space-y-0.5 text-xs text-zinc-500">
          {item.parts.map((p) => (
            <li key={p.pos_code || "manual"}>
              {p.pos_code ? `${p.pos_name}: ${new Big(p.sold_qty).toString()} × ${perUnit(p.per_unit_base)} = ${perUnit(p.qty_base)}` : `${t("sales.manualCorrection")}: ${new Big(p.qty_base).gt(0) ? "+" : ""}${perUnit(p.qty_base)}`}
            </li>
          ))}
        </ul>
      </td>
      <td className="py-2 pr-3 text-right font-semibold whitespace-nowrap">
        {editable && !covered ? (
          <label className="inline-flex items-center gap-1">
            <Input
              inputMode="decimal"
              aria-label={t("sales.used")}
              className={cn("w-24 text-right", !isDec(current.qty) && "border-red-400")}
              value={current.qty}
              onChange={(e) => onEdit({ ...current, qty: e.target.value.replace(",", ".") })}
            />
            <span className="text-xs font-normal text-zinc-500">{t(`units.short.${item.base_unit}`)}</span>
          </label>
        ) : (
          <>
            {qty(v.qtyBase.toString(), item).main}
            {qty(v.qtyBase.toString(), item).alt && <span className="block text-xs font-normal text-zinc-500">{qty(v.qtyBase.toString(), item).alt}</span>}
          </>
        )}
      </td>
      {item.balance_base !== null && (
        <td className={cn("py-2 pr-3 text-right whitespace-nowrap", low && "font-semibold text-red-700")}>
          {qty(item.balance_base, item).main}
          {after && !covered && (
            <span className={cn("block text-xs", low ? "text-red-700" : "text-zinc-500")}>
              → {qty(after.toString(), item).main}
              {low && ` · ${t("sales.runningOut")}`}
            </span>
          )}
        </td>
      )}
      <td className="py-2 text-right whitespace-nowrap text-zinc-600">
        {editable && !covered ? (
          <div className="inline-flex flex-col items-end gap-1">
            <label className="inline-flex items-center gap-1">
              <Input
                inputMode="decimal"
                aria-label={t("sales.pricePer", { unit: t(`units.one.${item.unit}`) })}
                className={cn("w-28 text-right", !isDec(current.price) && "border-red-400")}
                value={current.price}
                onChange={(e) => onEdit({ ...current, price: e.target.value.replace(",", ".") })}
              />
              <span className="text-xs text-zinc-500">/ {t(`units.short.${item.unit}`)}</span>
            </label>
            <span className="font-medium text-zinc-800">= {cur.format(v.amount)}</span>
          </div>
        ) : draft ? (
          cur.format(v.amount)
        ) : (
          money(item.amount)
        )}
      </td>
    </tr>
  );
}

function UnmappedBlock({ lines, report }: { lines: PosLine[]; report: SalesImport }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const admin = can("manage_catalog");
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [editing, setEditing] = useState<PosLine | null>(null);
  const mark = useMutation({
    mutationFn: () => api(`/pos-items/not-kitchen`, { method: "POST", body: { ids: [...picked] } }),
    onSuccess: () => {
      setPicked(new Set());
      void qc.invalidateQueries({ queryKey: ["sales-import", report.id] });
      void qc.invalidateQueries({ queryKey: ["pos-items"] });
    },
  });
  const ids = lines.map((l) => l.pos_item_id).filter((x): x is number => x !== null);
  return (
    <Card className="mb-4 border-amber-300 bg-amber-50 p-4">
      <h2 className="font-semibold text-amber-900">{t("sales.unmappedTitle", { count: lines.length })}</h2>
      <p className="mt-1 text-sm text-amber-900">{admin ? t("sales.unmappedExplainAdmin") : t("sales.unmappedExplainStaff")}</p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[28rem] text-sm">
          <thead className="text-left text-xs text-zinc-500">
            <tr>
              {admin && (
                <th className="w-8 py-1">
                  <input
                    type="checkbox"
                    aria-label={t("sales.selectAll")}
                    className="h-4 w-4"
                    checked={ids.length > 0 && picked.size === ids.length}
                    onChange={(e) => setPicked(e.target.checked ? new Set(ids) : new Set())}
                  />
                </th>
              )}
              <th className="py-1">{t("sales.posItem")}</th>
              <th className="py-1 text-right">{t("sales.sold")}</th>
              {admin && <th />}
            </tr>
          </thead>
          <tbody>
            {lines.map((l) => (
              <tr key={l.code} className="border-t border-amber-200">
                {admin && (
                  <td className="py-1.5">
                    {l.pos_item_id !== null && (
                      <input
                        type="checkbox"
                        aria-label={l.name}
                        className="h-4 w-4"
                        checked={picked.has(l.pos_item_id)}
                        onChange={(e) => {
                          const next = new Set(picked);
                          if (e.target.checked) next.add(l.pos_item_id!);
                          else next.delete(l.pos_item_id!);
                          setPicked(next);
                        }}
                      />
                    )}
                  </td>
                )}
                <td className="py-1.5">
                  {l.name} <span className="text-xs text-zinc-500">{l.code}</span>
                </td>
                <td className="py-1.5 text-right">{new Big(l.qty).toString()}</td>
                {admin && (
                  <td className="py-1.5 text-right">
                    {l.pos_item_id !== null && (
                      <button type="button" className="text-sm font-medium text-zinc-800 underline" onClick={() => setEditing(l)}>
                        {t("sales.setNorm")}
                      </button>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {admin && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button variant="secondary" disabled={picked.size === 0 || mark.isPending} onClick={() => mark.mutate()}>
            {t("sales.markNotKitchen", { count: picked.size })}
          </Button>
          {mark.error && <span className="text-sm text-red-700">{errorMessage(mark.error, t)}</span>}
        </div>
      )}
      {editing && editing.pos_item_id !== null && (
        <NormDialog item={{ id: editing.pos_item_id, code: editing.code, name: editing.name }} onClose={() => setEditing(null)} />
      )}
    </Card>
  );
}

function VoidDialog({ report, onClose }: { report: SalesImport; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [id] = useState(uuidv4);
  const v = useMutation({
    mutationFn: () => api<SalesImport>(`/sales-imports/${report.id}/void`, { method: "POST", body: { reversal_id: id } }),
    onSuccess: (r) => {
      qc.setQueryData(["sales-import", report.id, null], r);
      void qc.invalidateQueries();
      onClose();
    },
  });
  return (
    <Modal title={t("sales.voidTitle", { date: report.sales_date })} onClose={onClose}>
      <div className="space-y-4 text-sm">
        <p>{report.status === "posted" ? t("sales.voidExplainPosted") : t("sales.voidExplain")}</p>
        {v.error && <Alert>{errorMessage(v.error, t)}</Alert>}
        <div className="flex gap-2">
          <Button variant="danger" disabled={v.isPending} onClick={() => v.mutate()}>
            {t("sales.void")}
          </Button>
          <Button variant="secondary" onClick={onClose}>
            {t("common.cancel")}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function PostPanel({ report, locationId, lines, valid }: {
  report: SalesImport; locationId: number | null; lines: { product_id: number; qty_base: string; unit_price: string }[]; valid: boolean;
}) {
  const cur = useCurrency();
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [docId] = useState(uuidv4); // same id on every retry of this page's write-off
  const [ack, setAck] = useState(false);
  const done = (r: SalesImport) => {
    void qc.invalidateQueries();
    qc.setQueryData(["sales-import", report.id, locationId], r);
  };
  const post = useMutation({
    mutationFn: (allowNegative: boolean) =>
      api<SalesImport>(`/sales-imports/${report.id}/post`, {
        method: "POST",
        body: { document_id: docId, location_id: locationId, allow_negative: allowNegative, acknowledge_unmapped: ack, lines, price_currency: cur.code },
      }),
    onSuccess: done,
  });
  const discard = useMutation({
    mutationFn: () => api(`/sales-imports/${report.id}`, { method: "DELETE" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["sales-imports"] });
      navigate("/sales");
    },
  });
  const detail = post.error instanceof ApiError ? post.error.detail : undefined;
  const needsNegative = detail?.code === "insufficient_stock" && !!detail.can_override;
  const skipped = report.items.filter((i) => i.covered_inventory_id !== null).length;
  const blocked = report.unmapped.length > 0 && !ack;

  return (
    <div className="space-y-3">
      {report.unmapped.length > 0 && (
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" className="mt-0.5 h-4 w-4" checked={ack} onChange={(e) => setAck(e.target.checked)} />
          <span>{t("sales.ackUnmapped", { count: report.unmapped.length })}</span>
        </label>
      )}
      {skipped > 0 && <p className="text-sm text-amber-800">{t("sales.skipExplain", { count: skipped })}</p>}
      {post.error && <Alert>{errorMessage(post.error, t)}</Alert>}
      <div className="flex flex-wrap gap-2">
        {needsNegative ? (
          <Button variant="danger" disabled={post.isPending} onClick={() => post.mutate(true)}>
            {t("docs.postNegative")}
          </Button>
        ) : (
          <Button disabled={post.isPending || !locationId || blocked || !valid || report.items.length === 0} onClick={() => post.mutate(false)}>
            {t("sales.writeOff")}
          </Button>
        )}
        <Button variant="secondary" disabled={discard.isPending} onClick={() => discard.mutate()}>
          {t("sales.discard")}
        </Button>
      </div>
      {!locationId && <p className="text-xs text-zinc-500">{t("sales.pickLocation")}</p>}
    </div>
  );
}

export function SalesReportPage() {
  const { id } = useParams();
  const { t } = useTranslation();
  const { can } = useAuth();
  const dt = useDateTime();
  const locations = useActiveLocations().data ?? [];
  const [locationId, setLocationId] = useState<number | null>(rememberedLocation);
  const [openDoc, setOpenDoc] = useState<string | null>(null);
  const [voiding, setVoiding] = useState(false);
  const [editing, setEditing] = useState<PosLine | null>(null);
  const [edits, setEdits] = useState<Record<number, UsageEdit>>({});
  const cur = useCurrency();
  const loc = locationId !== null && locations.some((l) => l.id === locationId) ? locationId : null;
  const q = useQuery({
    queryKey: ["sales-import", id, loc],
    queryFn: () => api<SalesImport>(`/sales-imports/${id}${loc ? `?location_id=${loc}` : ""}`),
    placeholderData: (prev) => prev,
  });
  const r = q.data;
  if (q.error) return <Alert>{errorMessage(q.error, t)}</Alert>;
  if (!r) return <p className="text-sm text-zinc-500">{t("common.loading")}</p>;
  const draft = r.status === "draft";
  const editable = draft && can("post_write_off");
  // recalculated at once from what is typed (owner, 2026-11-25)
  const total = r.items.reduce((s, i) => s.plus(draft ? rowValues(i, edits[i.product_id], cur).amount : cur.toDisplay(i.amount)), new Big(0));
  const allValid = r.items.every((i) => rowValues(i, edits[i.product_id], cur).valid);
  const lines = r.items
    .filter((i) => edits[i.product_id] && i.covered_inventory_id === null)
    .map((i) => ({ product_id: i.product_id, qty_base: edits[i.product_id].qty.trim(), unit_price: edits[i.product_id].price.trim() }));

  return (
    <div>
      <Link to="/sales" className="mb-3 inline-flex items-center gap-1 text-sm text-zinc-600 hover:text-zinc-900">
        <ArrowLeft className="h-4 w-4" /> {t("nav.sales")}
      </Link>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">{t("sales.reportTitle", { date: r.sales_date })}</h1>
        <StatusBadge status={r.status} />
      </div>
      <dl className="mb-4 grid gap-3 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-xs text-zinc-500">{t("sales.file")}</dt>
          <dd className="break-all">{r.file_name || "—"}</dd>
        </div>
        <div>
          <dt className="text-xs text-zinc-500">{t("sales.uploadedBy")}</dt>
          <dd>
            {r.uploaded_by_name} · {dt(r.uploaded_at)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-zinc-500">{t("sales.itemsSold")}</dt>
          <dd>
            {new Big(r.total_qty).toString()} · {t("sales.positions", { count: r.line_count })}
          </dd>
        </div>
        {r.closed_by_name && r.closed_at && (
          <div>
            <dt className="text-xs text-zinc-500">{t(`sales.closedBy.${r.status}`)}</dt>
            <dd>
              {r.closed_by_name} · {dt(r.closed_at)}
            </dd>
          </div>
        )}
      </dl>

      {r.warnings.length > 0 && (
        <Card className="mb-4 border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
          <ul className="list-disc space-y-1 pl-5">
            {r.warnings.map((w, i) => (
              <Warning key={i} w={w} />
            ))}
          </ul>
        </Card>
      )}

      {r.status === "posted" && r.write_off_id && (
        <Card className="mb-4 flex flex-wrap items-center gap-3 p-4 text-sm">
          <span>{t("sales.postedAt", { location: r.location_name ?? "" })}</span>
          <Button variant="secondary" onClick={() => setOpenDoc(r.write_off_id)}>
            {t("sales.openDocument")}
          </Button>
        </Card>
      )}
      {r.status === "covered" && (
        <Card className="mb-4 p-4 text-sm">{t("sales.coveredBy", { id: String(r.covered_inventory_id ?? ""), location: r.location_name ?? "" })}</Card>
      )}
      {r.status === "voided" && <Card className="mb-4 p-4 text-sm text-zinc-600">{t("sales.voidedNote")}</Card>}

      {r.unmapped.length > 0 && r.status !== "voided" && <UnmappedBlock lines={r.unmapped} report={r} />}

      <Card className="mb-4 p-4">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <h2 className="font-semibold">{t("sales.usageTitle")}</h2>
          {draft && can("post_write_off") && (
            <div className="w-full sm:w-64">
              <Field label={t("sales.fromLocation")}>
                <LocationSelect
                  locations={locations}
                  value={loc}
                  onChange={(v) => {
                    setLocationId(v);
                    remember(v);
                  }}
                />
              </Field>
            </div>
          )}
        </div>
        {r.items.length === 0 ? (
          <p className="text-sm text-zinc-500">{t("sales.noUsage")}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[32rem] text-sm">
              <thead className="text-left text-xs text-zinc-500">
                <tr>
                  <th className="py-1 pr-3">{t("sales.product")}</th>
                  <th className="py-1 pr-3 text-right">{t("sales.used")}</th>
                  {r.items[0]?.balance_base !== null && <th className="py-1 pr-3 text-right">{t("sales.onHand")}</th>}
                  <th className="py-1 text-right">{t("sales.cost")}</th>
                </tr>
              </thead>
              <tbody>
                {r.items.map((i) => (
                  <UsageRow
                    key={i.product_id}
                    item={i}
                    draft={draft}
                    editable={editable}
                    edit={edits[i.product_id]}
                    onEdit={(e) => setEdits((x) => ({ ...x, [i.product_id]: e }))}
                  />
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t border-zinc-200 font-semibold">
                  <td className="py-2" colSpan={r.items[0]?.balance_base !== null ? 3 : 2}>
                    {t("sales.total")}
                  </td>
                  <td className="py-2 text-right">{cur.format(total)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
        {draft && can("post_write_off") && (
          <div className="mt-4 border-t border-zinc-100 pt-4">
            {editable && <p className="mb-3 text-xs text-zinc-500">{t("sales.editHint")}</p>}
            <PostPanel report={r} locationId={loc} lines={lines} valid={allValid} />
          </div>
        )}
        {(r.status === "posted" || r.status === "covered") && can("reverse_document") && (
          <div className="mt-4 border-t border-zinc-100 pt-4">
            <Button variant="secondary" onClick={() => setVoiding(true)}>
              {t("sales.voidAndReimport")}
            </Button>
          </div>
        )}
      </Card>

      {r.not_kitchen.length > 0 && (
        <details className="mb-4 rounded-xl border border-zinc-200 bg-white p-4 text-sm">
          <summary className="cursor-pointer font-medium">{t("sales.notKitchenTitle", { count: r.not_kitchen.length })}</summary>
          <ul className="mt-2 grid gap-1 sm:grid-cols-2">
            {r.not_kitchen.map((l) => (
              <li key={l.code} className="flex justify-between gap-2">
                <span>
                  {l.name} <span className="text-xs text-zinc-500">{l.code}</span>
                </span>
                <span className="flex items-center gap-2">
                  {new Big(l.qty).toString()}
                  {can("manage_catalog") && l.pos_item_id !== null && (
                    <button type="button" className="text-xs underline" onClick={() => setEditing(l)}>
                      {t("common.edit")}
                    </button>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}

      {openDoc && <DocumentView id={openDoc} onClose={() => setOpenDoc(null)} />}
      {voiding && <VoidDialog report={r} onClose={() => setVoiding(false)} />}
      {editing && editing.pos_item_id !== null && (
        <NormDialog item={{ id: editing.pos_item_id, code: editing.code, name: editing.name, not_kitchen: true, components: [] }} onClose={() => setEditing(null)} />
      )}
    </div>
  );
}
