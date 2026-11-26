import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import Big from "big.js";
import { useMemo, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/auth/AuthContext";
import { DataTable } from "@/components/DataTable";
import { Modal } from "@/components/Modal";
import { StockChart } from "@/components/StockChart";
import { Alert, Badge, Button, Field, Input, PageHeader, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useQty } from "@/lib/format";
import type { Category, Page, Product, ProductDetail } from "@/lib/types";
import { BASE_OF, fromBase, isContainer, plain, toBase, UNITS, type Unit } from "@/lib/units";

export function useCategoryName() {
  const { t } = useTranslation();
  return (c: { code: string | null; name: string }) => (c.code ? t(`categories.${c.code}`) : c.name);
}

function QtyCell({ p, qtyBase }: { p: Product; qtyBase: string }) {
  const q = useQty()(qtyBase, p);
  return (
    <span>
      {q.main}
      {q.alt && <span className="block text-xs text-zinc-500">{q.alt}</span>}
    </span>
  );
}

// ------------------------------------------------------------------------- form
interface Draft {
  name: string;
  sku: string;
  category_id: string;
  unit: Unit;
  unit_size: string; // ml per bottle
  min_stock: string; // in product unit
  barcode: string;
  full_weight_g: string;
  empty_weight_g: string;
}

function toDraft(p?: Product): Draft {
  if (!p)
    return { name: "", sku: "", category_id: "", unit: "bottle", unit_size: "700", min_stock: "0", barcode: "", full_weight_g: "", empty_weight_g: "" };
  return {
    name: p.name,
    sku: p.sku,
    category_id: String(p.category_id),
    unit: p.unit,
    unit_size: plain(new Big(p.unit_size)),
    min_stock: plain(fromBase(p.min_stock_base, p.unit, p)),
    barcode: p.barcode ?? "",
    full_weight_g: p.full_weight_g ?? "",
    empty_weight_g: p.empty_weight_g ?? "",
  };
}

const isNum = (s: string) => /^\d+(\.\d+)?$/.test(s.trim());

function ProductForm({ product, onDone }: { product?: Product; onDone: () => void }) {
  const { t } = useTranslation();
  const catName = useCategoryName();
  const qc = useQueryClient();
  const [d, setD] = useState<Draft>(() => toDraft(product));
  const [localError, setLocalError] = useState<string | null>(null);
  const cats = useQuery({ queryKey: ["categories"], queryFn: () => api<Category[]>("/categories") });
  const locked = !!product?.units_locked;
  const set = (patch: Partial<Draft>) => setD((x) => ({ ...x, ...patch }));

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      product ? api<ProductDetail>(`/products/${product.id}`, { method: "PATCH", body }) : api<ProductDetail>("/products", { method: "POST", body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["products"] });
      void qc.invalidateQueries({ queryKey: ["product"] });
      onDone();
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    setLocalError(null);
    const container = isContainer(d.unit);
    if (container && (!isNum(d.unit_size) || Number(d.unit_size) <= 0)) return setLocalError(t(d.unit === "pack" ? "products.errors.packSize" : "products.errors.bottleSize"));
    if (!isNum(d.min_stock)) return setLocalError(t("products.errors.number"));
    const unitInfo = { unit: d.unit, base_unit: BASE_OF[d.unit], unit_size: container ? d.unit_size : d.unit === "l" || d.unit === "kg" ? "1000" : "1" };
    const isBottle = d.unit === "bottle";
    const body: Record<string, unknown> = {
      name: d.name,
      sku: d.sku,
      category_id: Number(d.category_id),
      min_stock_base: toBase(d.min_stock, d.unit, unitInfo).toString(),
      barcode: d.barcode.trim() || null,
      full_weight_g: isBottle && d.full_weight_g.trim() ? d.full_weight_g.trim() : null,
      empty_weight_g: isBottle && d.empty_weight_g.trim() ? d.empty_weight_g.trim() : null,
    };
    if (!locked) {
      body.unit = d.unit;
      body.unit_size = container ? d.unit_size : null;
    }
    save.mutate(body);
  }

  const err = localError ?? (save.error ? errorMessage(save.error, t) : null);
  const activeCats = (cats.data ?? []).filter((c) => c.is_active || String(c.id) === d.category_id);

  return (
    <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
      {err && (
        <div className="sm:col-span-2">
          <Alert>{err}</Alert>
        </div>
      )}
      <div className="sm:col-span-2">
        <Field label={t("products.name")}>
          <Input value={d.name} onChange={(e) => set({ name: e.target.value })} required maxLength={128} autoFocus={!product} />
        </Field>
      </div>
      <Field label={t("products.sku")}>
        <Input value={d.sku} onChange={(e) => set({ sku: e.target.value })} required maxLength={64} autoCapitalize="characters" />
      </Field>
      <Field label={t("products.category")}>
        <Select value={d.category_id} onChange={(e) => set({ category_id: e.target.value })} required>
          <option value="" disabled>
            {t("common.select")}
          </option>
          {activeCats.map((c) => (
            <option key={c.id} value={c.id}>
              {catName(c)}
            </option>
          ))}
        </Select>
      </Field>
      <Field label={t("products.unit")} hint={locked ? t("products.unitsLocked") : undefined}>
        <Select
          value={d.unit}
          disabled={locked}
          onChange={(e) => {
            const u = e.target.value as Unit;
            // a sensible size when switching to a container: 700 ml bottle, 200 g pack
            set({ unit: u, unit_size: u === d.unit ? d.unit_size : u === "pack" ? "200" : u === "bottle" ? "700" : d.unit_size });
          }}
        >
          {UNITS.map((u) => (
            <option key={u} value={u}>
              {t(`units.long.${u}`)}
            </option>
          ))}
        </Select>
      </Field>
      {isContainer(d.unit) ? (
        <Field label={t(d.unit === "pack" ? "products.packSize" : "products.bottleSize")} hint={d.unit === "pack" ? t("products.packSizeHint") : undefined}>
          <Input inputMode="decimal" value={d.unit_size} disabled={locked} onChange={(e) => set({ unit_size: e.target.value })} required />
        </Field>
      ) : (
        <div className="hidden sm:block" />
      )}
      <Field label={t("products.minStockIn", { unit: t(`units.short.${d.unit}`) })} hint={t("products.minStockHint")}>
        <Input inputMode="decimal" value={d.min_stock} onChange={(e) => set({ min_stock: e.target.value })} required />
      </Field>
      <div className="sm:col-span-2">
        <Field label={t("products.barcode")}>
          <Input inputMode="numeric" value={d.barcode} onChange={(e) => set({ barcode: e.target.value })} maxLength={64} />
        </Field>
      </div>
      {d.unit === "bottle" && (
        <>
          <Field label={t("products.fullWeight")} hint={t("products.weightHint")}>
            <Input inputMode="decimal" value={d.full_weight_g} onChange={(e) => set({ full_weight_g: e.target.value })} />
          </Field>
          <Field label={t("products.emptyWeight")}>
            <Input inputMode="decimal" value={d.empty_weight_g} onChange={(e) => set({ empty_weight_g: e.target.value })} />
          </Field>
        </>
      )}
      <div className="flex gap-2 sm:col-span-2">
        <Button type="submit" disabled={save.isPending}>
          {product ? t("common.save") : t("common.create")}
        </Button>
        <Button variant="secondary" onClick={onDone}>
          {t("common.cancel")}
        </Button>
      </div>
    </form>
  );
}

// ----------------------------------------------------------------------- detail
export function ProductView({ id, onClose }: { id: number; onClose: () => void }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const fmt = useQty();
  const catName = useCategoryName();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const q = useQuery({ queryKey: ["product", id], queryFn: () => api<ProductDetail>(`/products/${id}`) });
  const toggle = useMutation({
    mutationFn: (active: boolean) => api<ProductDetail>(`/products/${id}`, { method: "PATCH", body: { is_active: active } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["products"] });
      void qc.invalidateQueries({ queryKey: ["product", id] });
    },
  });
  const p = q.data;

  return (
    <Modal title={p ? p.name : t("common.loading")} onClose={onClose} wide>
      {!p ? (
        <p className="text-sm text-zinc-500">{t("common.loading")}</p>
      ) : editing ? (
        <ProductForm product={p} onDone={() => setEditing(false)} />
      ) : (
        <div className="space-y-5">
          {toggle.error && <Alert>{errorMessage(toggle.error, t)}</Alert>}
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-3">
            {[
              [t("products.sku"), p.sku],
              [t("products.category"), catName({ code: p.category_code, name: p.category_name })],
              [t("products.unit"), p.unit === "bottle" ? `${t("units.long.bottle")} · ${plain(new Big(p.unit_size))} ml` : t(`units.long.${p.unit}`)],
              [t("products.minStock"), new Big(p.min_stock_base).gt(0) ? fmt(p.min_stock_base, p).main : "—"],
              [t("products.barcode"), p.barcode ?? "—"],
            ].map(([k, v]) => (
              <div key={k}>
                <dt className="text-xs text-zinc-500">{k}</dt>
                <dd className="font-medium">{v}</dd>
              </div>
            ))}
          </dl>

          <div>
            <h3 className="mb-2 text-sm font-semibold">{t("products.stockByLocation")}</h3>
            <div className="divide-y divide-zinc-100 rounded-lg border border-zinc-200">
              {p.balances.length === 0 && <p className="px-3 py-3 text-sm text-zinc-500">{t("products.noStock")}</p>}
              {p.balances.map((b) => {
                const f = fmt(b.qty_base, p);
                return (
                  <div key={b.location_id} className="flex items-center justify-between px-3 py-2 text-sm">
                    <span className={b.location_active ? "" : "text-zinc-400"}>{b.location_name}</span>
                    <span className="text-right tabular-nums">
                      {f.main}
                      {f.alt && <span className="block text-xs text-zinc-500">{f.alt}</span>}
                    </span>
                  </div>
                );
              })}
              <div className="flex items-center justify-between bg-zinc-50 px-3 py-2 text-sm font-semibold">
                <span>{t("products.total")}</span>
                <span className="text-right tabular-nums">
                  {fmt(p.total_qty_base, p).main}
                </span>
              </div>
            </div>
          </div>

          <StockChart productId={p.id} unit={p} />

          {can("manage_catalog") && (
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => setEditing(true)}>{t("common.edit")}</Button>
              <Button variant="secondary" disabled={toggle.isPending} onClick={() => toggle.mutate(!p.is_active)}>
                {p.is_active ? t("common.deactivate") : t("common.activate")}
              </Button>
              {p.is_active && new Big(p.total_qty_base).gt(0) && <p className="w-full text-xs text-amber-700">{t("products.deactivateWarning")}</p>}
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}

// ------------------------------------------------------------------------- page
type ActiveFilter = "active" | "inactive" | "all";

export function ProductsPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const catName = useCategoryName();
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [active, setActive] = useState<ActiveFilter>("active");
  const [lowOnly, setLowOnly] = useState(false);
  const [creating, setCreating] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);

  const cats = useQuery({ queryKey: ["categories"], queryFn: () => api<Category[]>("/categories") });
  const params = new URLSearchParams({ active, limit: "1000", ...(category ? { category_id: category } : {}), ...(lowOnly ? { low_stock: "true" } : {}) });
  const products = useQuery({ queryKey: ["products", params.toString()], queryFn: () => api<Page<Product>>(`/products?${params}`) });

  const columns = useMemo<ColumnDef<Product, unknown>[]>(
    () => [
      {
        id: "name",
        header: t("products.name"),
        accessorFn: (p) => p.name.toLowerCase(),
        cell: ({ row: { original: p } }) => (
          <div>
            <div className="font-medium">{p.name}</div>
            <div className="text-xs text-zinc-500">{p.sku}</div>
          </div>
        ),
      },
      { id: "category", header: t("products.category"), accessorFn: (p) => catName({ code: p.category_code, name: p.category_name }) },
      {
        id: "stock",
        header: t("products.inStock"),
        meta: { align: "right" },
        accessorFn: (p) => Number(p.total_qty_base),
        cell: ({ row: { original: p } }) => (
          <div className="inline-flex flex-col items-end gap-1">
            <QtyCell p={p} qtyBase={p.total_qty_base} />
            {p.is_low_stock && <Badge tone="red">{t("products.low")}</Badge>}
          </div>
        ),
      },
    ],
    [t, catName],
  );


  return (
    <>
      <PageHeader title={t("nav.products")} actions={can("manage_catalog") && <Button onClick={() => setCreating(true)}>{t("products.new")}</Button>} />
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Input type="search" placeholder={t("products.searchPlaceholder")} value={search} onChange={(e) => setSearch(e.target.value)} aria-label={t("common.search")} />
        <Select value={category} onChange={(e) => setCategory(e.target.value)} aria-label={t("products.category")}>
          <option value="">{t("products.allCategories")}</option>
          {cats.data?.map((c) => (
            <option key={c.id} value={c.id}>
              {catName(c)}
            </option>
          ))}
        </Select>
        <Select value={active} onChange={(e) => setActive(e.target.value as ActiveFilter)} aria-label={t("users.status")}>
          <option value="active">{t("common.active")}</option>
          <option value="inactive">{t("common.inactive")}</option>
          <option value="all">{t("common.all")}</option>
        </Select>
        <label className="flex min-h-10 items-center gap-2 text-sm">
          <input type="checkbox" className="h-4 w-4" checked={lowOnly} onChange={(e) => setLowOnly(e.target.checked)} />
          {t("products.lowOnly")}
        </label>
      </div>
      {products.error && (
        <div className="mb-4">
          <Alert>{errorMessage(products.error, t)}</Alert>
        </div>
      )}
      <DataTable
        data={products.data?.items}
        columns={columns}
        loading={products.isLoading}
        search={search}
        searchText={(p) => `${p.name} ${p.sku} ${p.barcode ?? ""}`}
        initialSort={[{ id: "name", desc: false }]}
        onRowClick={(p) => setOpenId(p.id)}
        rowClassName={(p) => (!p.is_active ? "text-zinc-400" : p.is_low_stock ? "bg-red-50 text-red-800" : undefined)}
        empty={t("products.empty")}
      />
      {products.data && (
        <p className="mt-3 text-sm text-zinc-500">
          {t("products.summary", { count: products.data.total })}
        </p>
      )}
      {creating && (
        <Modal title={t("products.new")} onClose={() => setCreating(false)} wide>
          <ProductForm onDone={() => setCreating(false)} />
        </Modal>
      )}
      {openId !== null && <ProductView id={openId} onClose={() => setOpenId(null)} />}
    </>
  );
}
