import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import Big from "big.js";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { DataTable } from "@/components/DataTable";
import { useActiveLocations } from "@/components/pickers";
import { Alert, Input, PageHeader, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useQty } from "@/lib/format";
import type { StockRow } from "@/lib/types";
import { ProductView, useCategoryName } from "./ProductsPage";

export function StockPage() {
  const { t } = useTranslation();
  const qty = useQty();
  const catName = useCategoryName();
  const locations = useActiveLocations();
  const [location, setLocation] = useState("");
  const [search, setSearch] = useState("");
  const [includeZero, setIncludeZero] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);

  const params = new URLSearchParams({ ...(location ? { location_id: location } : {}), ...(includeZero ? { include_zero: "true" } : {}) });
  const rows = useQuery({ queryKey: ["stock", params.toString()], queryFn: () => api<StockRow[]>(`/stock?${params}`) });

  const columns = useMemo<ColumnDef<StockRow, unknown>[]>(
    () => [
      {
        id: "product",
        header: t("products.name"),
        accessorFn: (r) => r.product_name.toLowerCase(),
        cell: ({ row: { original: r } }) => (
          <div>
            <div className="font-medium">{r.product_name}</div>
            <div className="text-xs text-zinc-500">
              {r.product_sku} · {catName({ code: r.category_code, name: r.category_name })}
            </div>
          </div>
        ),
      },
      { id: "location", header: t("docs.location"), accessorFn: (r) => r.location_name },
      {
        id: "qty",
        header: t("docs.qty"),
        meta: { align: "right" },
        accessorFn: (r) => Number(r.qty_base),
        cell: ({ row: { original: r } }) => {
          const f = qty(r.qty_base, r);
          return (
            <span className={new Big(r.qty_base).lt(0) || r.is_low_stock ? "font-semibold text-red-700" : ""}>
              {f.main}
              {r.is_low_stock && <span className="block text-xs font-normal">{t("products.low")}</span>}
              {f.alt && <span className="block text-xs text-zinc-500">{f.alt}</span>}
            </span>
          );
        },
      },
    ],
    [t, qty, catName],
  );


  return (
    <>
      <PageHeader title={t("nav.stock")} />
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Input type="search" placeholder={t("products.searchPlaceholder")} value={search} onChange={(e) => setSearch(e.target.value)} aria-label={t("common.search")} />
        <Select value={location} onChange={(e) => setLocation(e.target.value)} aria-label={t("docs.location")}>
          <option value="">{t("stock.allLocations")}</option>
          {locations.data?.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name}
            </option>
          ))}
        </Select>
        <label className="flex min-h-10 items-center gap-2 text-sm">
          <input type="checkbox" className="h-4 w-4" checked={includeZero} onChange={(e) => setIncludeZero(e.target.checked)} />
          {t("stock.includeZero")}
        </label>
      </div>
      {rows.error && (
        <div className="mb-4">
          <Alert>{errorMessage(rows.error, t)}</Alert>
        </div>
      )}
      <DataTable
        data={rows.data}
        columns={columns}
        rowClassName={(r) => (r.is_low_stock ? "bg-red-50" : undefined)}
        loading={rows.isLoading}
        search={search}
        searchText={(r) => `${r.product_name} ${r.product_sku} ${r.location_name}`}
        initialSort={[{ id: "product", desc: false }]}
        empty={t("stock.empty")}
        onRowClick={(r) => setOpenId(r.product_id)}
      />
      {openId !== null && <ProductView id={openId} onClose={() => setOpenId(null)} />}
    </>
  );
}
