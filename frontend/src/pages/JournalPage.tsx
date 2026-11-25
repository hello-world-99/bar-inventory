import { useQuery } from "@tanstack/react-query";
import Big from "big.js";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ProductPicker, useActiveLocations, useActiveProducts } from "@/components/pickers";
import { Alert, Badge, Button, Input, PageHeader, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useDateTime, useQty } from "@/lib/format";
import type { DocType, Movement, Page } from "@/lib/types";
import { DocumentView } from "./documents/DocumentView";

const TYPES: DocType[] = ["receipt", "write_off", "transfer", "inventory_adjustment", "reversal"];
const PAGE = 100;

export function JournalPage() {
  const { t } = useTranslation();
  const qty = useQty();
  const dt = useDateTime();
  const products = useActiveProducts().data ?? [];
  const locations = useActiveLocations().data ?? [];
  const [type, setType] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [product, setProduct] = useState<number | null>(null);
  const [location, setLocation] = useState("");
  const [page, setPage] = useState(0);
  const [openDoc, setOpenDoc] = useState<string | null>(null);

  const params = new URLSearchParams({ limit: String(PAGE), offset: String(page * PAGE) });
  if (type) params.set("type", type);
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);
  if (product) params.set("product_id", String(product));
  if (location) params.set("location_id", location);
  const q = useQuery({ queryKey: ["journal", params.toString()], queryFn: () => api<Page<Movement>>(`/journal?${params}`) });
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / PAGE)) : 1;
  const reset = <T,>(fn: (v: T) => void) => (v: T) => {
    fn(v);
    setPage(0);
  };

  return (
    <>
      <PageHeader title={t("nav.journal")} />
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Select value={type} onChange={(e) => reset(setType)(e.target.value)} aria-label={t("journal.type")}>
          <option value="">{t("journal.allTypes")}</option>
          {TYPES.map((x) => (
            <option key={x} value={x}>
              {t(`docTypes.${x}`)}
            </option>
          ))}
        </Select>
        <div className="flex gap-2">
          <ProductPicker products={products} value={product} onChange={(p) => reset(setProduct)(p.id)} />
          {product && (
            <Button variant="ghost" onClick={() => reset(setProduct)(null)} aria-label={t("journal.clearProduct")}>
              ×
            </Button>
          )}
        </div>
        <Select value={location} onChange={(e) => reset(setLocation)(e.target.value)} aria-label={t("docs.location")}>
          <option value="">{t("stock.allLocations")}</option>
          {locations.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name}
            </option>
          ))}
        </Select>
        <Input type="date" value={from} onChange={(e) => reset(setFrom)(e.target.value)} aria-label={t("docs.dateFrom")} />
        <Input type="date" value={to} onChange={(e) => reset(setTo)(e.target.value)} aria-label={t("docs.dateTo")} />
      </div>
      {q.error && (
        <div className="mb-4">
          <Alert>{errorMessage(q.error, t)}</Alert>
        </div>
      )}
      <div className="overflow-x-auto rounded-xl border border-zinc-200 bg-white">
        <table className="w-full min-w-[760px] text-sm">
          <thead className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500">
            <tr>
              <th className="px-4 py-3 font-medium">{t("docs.date")}</th>
              <th className="px-4 py-3 font-medium">{t("journal.type")}</th>
              <th className="px-4 py-3 font-medium">{t("products.name")}</th>
              <th className="px-4 py-3 font-medium">{t("docs.location")}</th>
              <th className="px-4 py-3 text-right font-medium">{t("journal.change")}</th>
              <th className="px-4 py-3 text-right font-medium">{t("journal.balance")}</th>
              <th className="px-4 py-3 font-medium">{t("docs.author")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100">
            {q.isLoading && (
              <tr>
                <td colSpan={8} className="px-4 py-8 text-center text-zinc-500">
                  {t("common.loading")}
                </td>
              </tr>
            )}
            {q.data?.items.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-8 text-center text-zinc-500">
                  {t("journal.empty")}
                </td>
              </tr>
            )}
            {q.data?.items.map((m) => {
              const d = qty(m.delta_base, m);
              const positive = new Big(m.delta_base).gt(0);
              return (
                <tr key={m.id} className="cursor-pointer hover:bg-zinc-50" onClick={() => setOpenDoc(m.document_id)}>
                  <td className="whitespace-nowrap px-4 py-2">{dt(m.doc_date)}</td>
                  <td className="px-4 py-2">
                    <Badge tone={m.doc_type === "receipt" ? "green" : m.doc_type === "write_off" ? "red" : m.doc_type === "inventory_adjustment" ? "amber" : "neutral"}>
                      {t(`docTypes.${m.doc_type}`)}
                    </Badge>
                    {m.reason && <div className="mt-0.5 text-xs text-zinc-500">{t(`reasons.${m.reason}`)}</div>}
                  </td>
                  <td className="px-4 py-2">
                    <div className="font-medium">{m.product_name}</div>
                    <div className="text-xs text-zinc-500">{m.product_sku}</div>
                  </td>
                  <td className="px-4 py-2">{m.location_name}</td>
                  <td className={`px-4 py-2 text-right tabular-nums ${positive ? "text-emerald-700" : "text-red-700"}`}>
                    {positive ? "+" : ""}
                    {d.main}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">{qty(m.balance_after, m).main}</td>
                  <td className="px-4 py-2">{m.user_name}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {q.data && q.data.total > PAGE && (
        <div className="mt-3 flex items-center gap-3 text-sm">
          <Button variant="secondary" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
            ←
          </Button>
          <span>{t("journal.page", { page: page + 1, pages })}</span>
          <Button variant="secondary" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>
            →
          </Button>
        </div>
      )}
      {openDoc && <DocumentView id={openDoc} onClose={() => setOpenDoc(null)} />}
    </>
  );
}
