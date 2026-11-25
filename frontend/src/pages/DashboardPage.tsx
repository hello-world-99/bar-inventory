import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ChevronRight } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Alert, Badge, Card, cn, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useDateTime, useQty } from "@/lib/format";
import type { Dashboard, DocSummary } from "@/lib/types";
import { DocumentView } from "./documents/DocumentView";
import { statusTone } from "./inventory/InventoryListPage";

/** Requirements 2.1: positions, stock value, current stock, low stock, recent receipts and write-offs, recent counts. */
export function DashboardPage() {
  const { t } = useTranslation();
  const qty = useQty();
  const dt = useDateTime();
  const [openDoc, setOpenDoc] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dashboard>("/dashboard"), refetchInterval: 60_000 });
  const d = q.data;

  return (
    <>
      <PageHeader title={t("dashboard.title")} />
      {q.error && <Alert>{errorMessage(q.error, t)}</Alert>}
      {!d ? (
        !q.error && <p className="text-sm text-zinc-500">{t("common.loading")}</p>
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
            <Stat
              label={t("dashboard.products")}
              value={String(d.product_count)}
              hint={t("dashboard.inStock", { count: d.in_stock_count })}
              to="/products"
            />
            <Stat
              label={t("dashboard.lowStock")}
              value={String(d.low_stock_count)}
              hint={d.low_stock_count ? t("dashboard.lowStockHint") : t("dashboard.allAboveMin")}
              warn={d.low_stock_count > 0}
            />
            <Stat
              label={t("dashboard.negative")}
              value={String(d.negative_count)}
              hint={d.negative_count ? t("dashboard.negativeHint") : t("dashboard.noNegative")}
              warn={d.negative_count > 0}
              to="/stock"
            />
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <Section title={t("dashboard.byLocation")} link={{ to: "/stock", label: t("dashboard.openStock") }}>
              {d.by_location.length === 0 ? (
                <Empty>{t("stock.empty")}</Empty>
              ) : (
                <ul className="divide-y divide-zinc-100">
                  {d.by_location.map((l) => (
                    <li key={l.location_id} className="flex items-center justify-between gap-3 py-2.5">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-sm font-medium">{l.name}</span>
                          {!l.is_active && <Badge>{t("common.inactive")}</Badge>}
                        </div>
                        <div className="text-xs text-zinc-500">{t("dashboard.positions", { count: l.product_count })}</div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Section>

            <Section title={t("dashboard.lowStock")} link={{ to: "/products", label: t("dashboard.openProducts") }}>
              {d.low_stock.length === 0 ? (
                <Empty>{t("dashboard.allAboveMin")}</Empty>
              ) : (
                <ul className="divide-y divide-zinc-100">
                  {d.low_stock.map((p) => (
                    <li key={p.product_id} className="flex items-center justify-between gap-3 py-2.5">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium">{p.name}</div>
                        <div className="text-xs text-zinc-500">{p.sku}</div>
                      </div>
                      <div className="text-right text-sm tabular-nums">
                        <div className="font-semibold text-red-700">{qty(p.total_qty_base, p).main}</div>
                        <div className="text-xs text-zinc-500">{t("dashboard.min", { qty: qty(p.min_stock_base, p).main })}</div>
                      </div>
                    </li>
                  ))}
                  {d.low_stock_count > d.low_stock.length && (
                    <li className="pt-2.5 text-xs text-zinc-500">{t("dashboard.more", { count: d.low_stock_count - d.low_stock.length })}</li>
                  )}
                </ul>
              )}
            </Section>

            <Section title={t("dashboard.recentReceipts")} link={{ to: "/receipts", label: t("dashboard.openAll") }}>
              <DocList docs={d.recent_receipts} onOpen={setOpenDoc} detail={(x) => x.supplier || x.invoice_no || x.comment} />
            </Section>

            <Section title={t("dashboard.recentWriteOffs")} link={{ to: "/write-offs", label: t("dashboard.openAll") }}>
              <DocList docs={d.recent_write_offs} onOpen={setOpenDoc} detail={(x) => (x.reason ? t(`reasons.${x.reason}`) : x.comment)} />
            </Section>
          </div>

          <Section title={t("dashboard.recentCounts")} link={{ to: "/inventory", label: t("dashboard.openAll") }}>
            {d.recent_inventories.length === 0 ? (
              <Empty>{t("inventory.empty")}</Empty>
            ) : (
              <ul className="divide-y divide-zinc-100">
                {d.recent_inventories.map((inv) => (
                  <li key={inv.id}>
                    <Link to={`/inventory/${inv.id}`} className="-mx-2 flex items-center justify-between gap-3 rounded-lg px-2 py-2.5 hover:bg-zinc-50">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="truncate text-sm font-medium">{inv.location_name}</span>
                          <Badge tone={statusTone(inv.status)}>{t(`inventory.status.${inv.status}`)}</Badge>
                        </div>
                        <div className="text-xs text-zinc-500">
                          {inv.status === "in_progress"
                            ? t("inventory.progress", { counted: inv.counted_count, total: inv.line_count })
                            : `${dt(inv.closed_at ?? inv.started_at)} · ${inv.closed_by_name ?? ""}`}
                        </div>
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </div>
      )}
      {openDoc && <DocumentView id={openDoc} onClose={() => setOpenDoc(null)} />}
    </>
  );
}

function Stat({ label, value, hint, warn, to }: { label: string; value: string; hint?: string; warn?: boolean; to?: string }) {
  const body = (
    <Card className={cn("h-full", to && "transition-colors hover:border-zinc-400")}>
      <div className="flex items-center gap-1.5 text-xs font-medium text-zinc-500">
        {warn && <AlertTriangle className="h-3.5 w-3.5 text-amber-600" aria-hidden />}
        {label}
      </div>
      <div className="mt-1 truncate text-2xl font-semibold tabular-nums tracking-tight">{value}</div>
      {hint && <div className={cn("mt-1 text-xs", warn ? "text-amber-700" : "text-zinc-500")}>{hint}</div>}
    </Card>
  );
  return to ? (
    <Link to={to} className="block">
      {body}
    </Link>
  ) : (
    body
  );
}

function Section({ title, link, children }: { title: string; link?: { to: string; label: string }; children: ReactNode }) {
  return (
    <Card>
      <div className="mb-2 flex items-center justify-between gap-3">
        <h2 className="font-semibold">{title}</h2>
        {link && (
          <Link to={link.to} className="inline-flex items-center text-sm text-zinc-600 hover:text-zinc-900">
            {link.label}
            <ChevronRight className="h-4 w-4" aria-hidden />
          </Link>
        )}
      </div>
      {children}
    </Card>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="py-2 text-sm text-zinc-500">{children}</p>;
}

function DocList({ docs, onOpen, detail }: { docs: DocSummary[]; onOpen: (id: string) => void; detail: (d: DocSummary) => string }) {
  const { t } = useTranslation();
  const dt = useDateTime();
  if (docs.length === 0) return <Empty>{t("dashboard.nothingYet")}</Empty>;
  return (
    <ul className="divide-y divide-zinc-100">
      {docs.map((x) => (
        <li key={x.id}>
          <button type="button" onClick={() => onOpen(x.id)} className="-mx-2 flex w-[calc(100%+1rem)] items-center justify-between gap-3 rounded-lg px-2 py-2.5 text-left hover:bg-zinc-50">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span>{dt(x.doc_date)}</span>
                {x.reversed_by && <Badge>{t("dashboard.reversed")}</Badge>}
              </div>
              <div className="truncate text-xs text-zinc-500">
                {[detail(x), t("dashboard.lines", { count: x.line_count }), x.created_by_name].filter(Boolean).join(" · ")}
              </div>
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}
