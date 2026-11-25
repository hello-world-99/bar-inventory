import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Big from "big.js";
import { Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { BalanceText } from "@/components/BalanceText";
import { LocationSelect, ProductPicker, QtyField, useActiveLocations, useActiveProducts } from "@/components/pickers";
import { Alert, Button, Field, Input, Select } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useAppSettings, useQty } from "@/lib/format";
import { nowLocalIn, zonedLocalToIso } from "@/lib/tz";
import { WRITE_OFF_REASONS, type Location, type Product, type StockDocument, type StockRow, type WriteOffReason } from "@/lib/types";
import { toBase, type Unit } from "@/lib/units";
import { uuidv4 } from "@/lib/uuid";

interface Line {
  key: string;
  product_id: number | null;
  location_id: number | null;
  qty: string;
  qty_unit: Unit | null;
}

const newLine = (location_id: number | null = null): Line => ({ key: uuidv4(), product_id: null, location_id, qty: "", qty_unit: null });
const isNum = (s: string) => /^\d+(\.\d+)?$/.test(s.trim());

/**
 * Shared submit flow. The document id is generated once per form, so resubmitting after a network error
 * or after confirming an override is the same request to the server (idempotent).
 */
function useDocSubmit(path: string, onDone: (d: StockDocument) => void) {
  const qc = useQueryClient();
  const [id] = useState(uuidv4);
  const done = (d: StockDocument) => {
    void qc.invalidateQueries();
    onDone(d);
  };
  const m = useMutation({
    mutationFn: (body: Record<string, unknown>) => api<StockDocument>(path, { method: "POST", body: { id, ...body } }),
    onSuccess: done,
    onError: (err) => {
      // The first attempt was posted but its response was lost (weak Wi-Fi), then the form was edited:
      // the server keeps the posted document. Show it instead of a confusing conflict.
      if (err instanceof ApiError && err.detail?.code === "id_conflict") {
        api<StockDocument>(`/documents/${id}`).then(done, () => undefined);
      }
    },
  });
  const detail = m.error instanceof ApiError ? m.error.detail : undefined;
  return {
    m,
    needsNegative: detail?.code === "insufficient_stock" && !!detail.can_override,
    needsBackdate: detail?.code === "backdate_confirmation_required",
  };
}

function DocHeader({ date, setDate, comment, setComment, children }: { date: string; setDate: (v: string) => void; comment: string; setComment: (v: string) => void; children?: ReactNode }) {
  const { t } = useTranslation();
  const tz = useTimeZone();
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {children}
      <Field label={`${t("docs.date")} (${tz})`} hint={t("docs.dateHint")}>
        <Input type="datetime-local" value={date} max={nowLocalIn(tz)} onChange={(e) => setDate(e.target.value)} />
      </Field>
      <div className="sm:col-span-2">
        <Field label={t("docs.comment")}>
          <Input value={comment} onChange={(e) => setComment(e.target.value)} maxLength={1000} />
        </Field>
      </div>
    </div>
  );
}

function SubmitBar({ pending, needsNegative, needsBackdate, onSubmit, onCancel, onOverride }: {
  pending: boolean; needsNegative: boolean; needsBackdate: boolean; onSubmit?: () => void; onCancel: () => void; onOverride: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap gap-2">
      {needsNegative || needsBackdate ? (
        <Button variant="danger" disabled={pending} onClick={onOverride}>
          {needsNegative ? t("docs.postNegative") : t("docs.postBackdated")}
        </Button>
      ) : (
        <Button type="submit" disabled={pending} onClick={onSubmit}>
          {t("docs.post")}
        </Button>
      )}
      <Button variant="secondary" onClick={onCancel}>
        {t("common.cancel")}
      </Button>
    </div>
  );
}

/** Current balances by product and place, for "in stock now -> after this line" in the forms (owner, reply 73). */
function useStockMap() {
  const q = useQuery({ queryKey: ["stock", "map"], queryFn: () => api<StockRow[]>("/stock?include_zero=true") });
  const map = new Map<string, StockRow>();
  for (const r of q.data ?? []) map.set(`${r.product_id}-${r.location_id}`, r);
  return map;
}

function StockMoves({ p, base, moves, locations }: { p: Product; base: string | null; moves: Move[]; locations: Location[] }) {
  const { t } = useTranslation();
  const stock = useStockMap();
  const shown = moves.filter((m) => m.location_id !== null);
  if (!shown.length) return null;
  return (
    <div className="mt-1 space-y-0.5 text-xs text-zinc-500">
      {shown.map((m) => {
        const now = stock.get(`${p.id}-${m.location_id}`)?.qty_base ?? "0";
        const after = base ? new Big(now).plus(new Big(base).times(m.sign)).toString() : null;
        const place = locations.find((l) => l.id === m.location_id)?.name ?? "";
        return (
          <div key={`${m.location_id}-${m.sign}`}>
            {t("docs.inStock", { place })} <BalanceText qtyBase={now} unit={p} min={p.min_stock_base} />
            {after !== null && (
              <>
                {" → "}
                <BalanceText qtyBase={after} unit={p} min={p.min_stock_base} />
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}

interface Move {
  location_id: number | null;
  sign: 1 | -1;
}

function LineRow({ line, products, locations, showLocation, onChange, onRemove, stockHint, moves = [] }: {
  line: Line; products: Product[]; locations: Location[]; showLocation: boolean;
  onChange: (l: Line) => void; onRemove?: () => void; stockHint?: ReactNode; moves?: Move[];
}) {
  const { t } = useTranslation();
  const p = products.find((x) => x.id === line.product_id) ?? null;
  let base: string | null = null;
  try {
    if (p && isNum(line.qty)) base = toBase(line.qty, line.qty_unit ?? p.unit, p).toString();
  } catch {
    base = null;
  }
  const fmt = useQty();
  return (
    <div className="grid gap-3 rounded-lg border border-zinc-200 p-3 sm:grid-cols-12 sm:items-start">
      <div className="sm:col-span-4">
        <ProductPicker products={products} value={line.product_id} onChange={(np) => onChange({ ...line, product_id: np.id, qty_unit: np.unit })} />
        {stockHint}
      </div>
      {showLocation && (
        <div className="sm:col-span-3">
          <LocationSelect locations={locations} value={line.location_id} onChange={(id) => onChange({ ...line, location_id: id })} />
        </div>
      )}
      <div className={showLocation ? "sm:col-span-3" : "sm:col-span-4"}>
        <QtyField product={p} qty={line.qty} unit={line.qty_unit} onChange={(qty, qty_unit) => onChange({ ...line, qty, qty_unit })} />
        {p && base && (line.qty_unit ?? p.unit) !== p.unit && <p className="mt-1 text-xs text-zinc-500">= {fmt(base, p).main}</p>}
        {p && <StockMoves p={p} base={base} moves={moves} locations={locations} />}
      </div>
      {onRemove && (
        <button type="button" onClick={onRemove} aria-label={t("docs.removeLine")} className="justify-self-end rounded-lg p-2 text-zinc-500 hover:bg-zinc-100 sm:col-span-1 sm:col-start-12 sm:row-start-1">
          <Trash2 className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}

function validate(lines: Line[], needLocation: boolean, t: (k: string) => string): string | null {
  for (const l of lines) {
    if (!l.product_id) return t("docs.errors.product");
    if (needLocation && !l.location_id) return t("docs.errors.location");
    if (!isNum(l.qty) || Number(l.qty) <= 0) return t("docs.errors.qty");
  }
  return null;
}

/** The form's wall-clock value is in the installation's time zone, not the device's (reply 17, P2). */
const isoOrUndefined = (local: string, tz: string) => (local ? zonedLocalToIso(local, tz) : undefined);

function useTimeZone(): string {
  return useAppSettings().data?.timezone ?? "UTC";
}

function useLines(initialLocation: number | null = null) {
  const [lines, setLines] = useState<Line[]>([newLine(initialLocation)]);
  return {
    lines,
    update: (i: number, l: Line) => setLines((ls) => ls.map((x, j) => (j === i ? l : x))),
    add: () => setLines((ls) => [...ls, newLine(ls[ls.length - 1]?.location_id ?? null)]),
    remove: (i: number) => setLines((ls) => ls.filter((_, j) => j !== i)),
  };
}

// --------------------------------------------------------------------- receipt
export function ReceiptForm({ onDone, onCancel }: { onDone: (d: StockDocument) => void; onCancel: () => void }) {
  const { t } = useTranslation();
  const products = useActiveProducts().data ?? [];
  const locations = useActiveLocations().data ?? [];
  const { lines, update, add, remove } = useLines();
  const [supplier, setSupplier] = useState("");
  const [invoice, setInvoice] = useState("");
  const [date, setDate] = useState("");
  const [comment, setComment] = useState("");
  const [localErr, setLocalErr] = useState<string | null>(null);
  const { m, needsBackdate } = useDocSubmit("/receipts", onDone);
  const tz = useTimeZone();


  function send(confirm = false) {
    const err = validate(lines, true, t);
    setLocalErr(err);
    if (err) return;
    m.mutate({
      supplier: supplier || null, invoice_no: invoice || null, comment, doc_date: isoOrUndefined(date, tz), confirm_backdate: confirm,
      // no prices in receipts (owner, reply 59): the server uses the product's price as the cost
      lines: lines.map((l) => ({ product_id: l.product_id, location_id: l.location_id, qty: l.qty, qty_unit: l.qty_unit })),
    });
  }

  return (
    <form onSubmit={(e: FormEvent) => (e.preventDefault(), send())} className="space-y-5">
      {(localErr || m.error) && <Alert>{localErr ?? errorMessage(m.error, t)}</Alert>}
      <DocHeader date={date} setDate={setDate} comment={comment} setComment={setComment}>
        <Field label={t("docs.supplier")}>
          <Input value={supplier} onChange={(e) => setSupplier(e.target.value)} maxLength={128} />
        </Field>
        <Field label={t("docs.invoice")}>
          <Input value={invoice} onChange={(e) => setInvoice(e.target.value)} maxLength={64} />
        </Field>
      </DocHeader>
      <div className="space-y-2">
        <h3 className="text-sm font-semibold">{t("docs.lines")}</h3>
        {lines.map((l, i) => (
          <LineRow key={l.key} moves={[{ location_id: l.location_id, sign: 1 }]} line={l} products={products} locations={locations} showLocation onChange={(x) => update(i, x)} onRemove={lines.length > 1 ? () => remove(i) : undefined} />
        ))}
        <div className="flex items-center justify-between">
          <Button variant="ghost" onClick={add}>
            <Plus className="h-4 w-4" /> {t("docs.addLine")}
          </Button>
        </div>
      </div>
      <SubmitBar pending={m.isPending} needsNegative={false} needsBackdate={needsBackdate} onCancel={onCancel} onOverride={() => send(true)} />
    </form>
  );
}

// ------------------------------------------------------------------- write-off
export function WriteOffForm({ onDone, onCancel }: { onDone: (d: StockDocument) => void; onCancel: () => void }) {
  const { t } = useTranslation();
  const products = useActiveProducts().data ?? [];
  const locations = useActiveLocations().data ?? [];
  const { lines, update, add, remove } = useLines();
  const [reason, setReason] = useState<WriteOffReason | "">("");
  const [date, setDate] = useState("");
  const [comment, setComment] = useState("");
  const [localErr, setLocalErr] = useState<string | null>(null);
  const { m, needsNegative, needsBackdate } = useDocSubmit("/write-offs", onDone);
  const tz = useTimeZone();

  function send(override = false) {
    const err = !reason ? t("docs.errors.reason") : validate(lines, true, t);
    setLocalErr(err);
    if (err) return;
    m.mutate({
      reason, comment, doc_date: isoOrUndefined(date, tz),
      allow_negative: override && needsNegative, confirm_backdate: override && needsBackdate,
      lines: lines.map((l) => ({ product_id: l.product_id, location_id: l.location_id, qty: l.qty, qty_unit: l.qty_unit })),
    });
  }

  return (
    <form onSubmit={(e: FormEvent) => (e.preventDefault(), send())} className="space-y-5">
      {(localErr || m.error) && <Alert>{localErr ?? errorMessage(m.error, t)}</Alert>}
      <DocHeader date={date} setDate={setDate} comment={comment} setComment={setComment}>
        <Field label={t("docs.reason")}>
          <Select value={reason} onChange={(e) => setReason(e.target.value as WriteOffReason)} required>
            <option value="" disabled>
              {t("common.select")}
            </option>
            {WRITE_OFF_REASONS.map((r) => (
              <option key={r} value={r}>
                {t(`reasons.${r}`)}
              </option>
            ))}
          </Select>
        </Field>
        <div className="hidden sm:block" />
      </DocHeader>
      <div className="space-y-2">
        <h3 className="text-sm font-semibold">{t("docs.lines")}</h3>
        {lines.map((l, i) => (
          <LineRow key={l.key} moves={[{ location_id: l.location_id, sign: -1 }]} line={l} products={products} locations={locations} showLocation onChange={(x) => update(i, x)} onRemove={lines.length > 1 ? () => remove(i) : undefined} />
        ))}
        <Button variant="ghost" onClick={add}>
          <Plus className="h-4 w-4" /> {t("docs.addLine")}
        </Button>
      </div>
      <SubmitBar pending={m.isPending} needsNegative={needsNegative} needsBackdate={needsBackdate} onCancel={onCancel} onOverride={() => send(true)} />
    </form>
  );
}

// -------------------------------------------------------------------- transfer
export function TransferForm({ onDone, onCancel }: { onDone: (d: StockDocument) => void; onCancel: () => void }) {
  const { t } = useTranslation();
  const products = useActiveProducts().data ?? [];
  const locations = useActiveLocations().data ?? [];
  const { lines, update, add, remove } = useLines();
  const [from, setFrom] = useState<number | null>(null);
  const [to, setTo] = useState<number | null>(null);
  const [date, setDate] = useState("");
  const [comment, setComment] = useState("");
  const [localErr, setLocalErr] = useState<string | null>(null);
  const { m, needsNegative, needsBackdate } = useDocSubmit("/transfers", onDone);
  const tz = useTimeZone();

  function send(override = false) {
    const err = !from || !to ? t("docs.errors.fromTo") : validate(lines, false, t);
    setLocalErr(err);
    if (err) return;
    m.mutate({
      from_location_id: from, to_location_id: to, comment, doc_date: isoOrUndefined(date, tz),
      allow_negative: override && needsNegative, confirm_backdate: override && needsBackdate,
      lines: lines.map((l) => ({ product_id: l.product_id, qty: l.qty, qty_unit: l.qty_unit })),
    });
  }

  return (
    <form onSubmit={(e: FormEvent) => (e.preventDefault(), send())} className="space-y-5">
      {(localErr || m.error) && <Alert>{localErr ?? errorMessage(m.error, t)}</Alert>}
      <DocHeader date={date} setDate={setDate} comment={comment} setComment={setComment}>
        <Field label={t("docs.from")}>
          <LocationSelect locations={locations} value={from} onChange={setFrom} exclude={to} />
        </Field>
        <Field label={t("docs.to")}>
          <LocationSelect locations={locations} value={to} onChange={setTo} exclude={from} />
        </Field>
      </DocHeader>
      <div className="space-y-2">
        <h3 className="text-sm font-semibold">{t("docs.lines")}</h3>
        {lines.map((l, i) => (
          <LineRow key={l.key} moves={[{ location_id: from, sign: -1 }, { location_id: to, sign: 1 }]} line={l} products={products} locations={locations} showLocation={false} onChange={(x) => update(i, x)} onRemove={lines.length > 1 ? () => remove(i) : undefined} />
        ))}
        <Button variant="ghost" onClick={add}>
          <Plus className="h-4 w-4" /> {t("docs.addLine")}
        </Button>
      </div>
      <SubmitBar pending={m.isPending} needsNegative={needsNegative} needsBackdate={needsBackdate} onCancel={onCancel} onOverride={() => send(true)} />
    </form>
  );
}
