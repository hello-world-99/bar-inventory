import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { DataTable } from "@/components/DataTable";
import { Alert, Badge, Input, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useQty } from "@/lib/format";
import type { PosComponent, PosItem } from "@/lib/types";
import { baseUnitInfo } from "@/lib/units";
import { NormDialog } from "./NormDialog";

function NormText({ c }: { c: PosComponent }) {
  const qty = useQty();
  // norms are small (grams, pieces): show them in the base unit rather than "0.35 kg"
  return (
    <span>
      {c.product_name} {qty(c.qty_base, baseUnitInfo(c)).main}
    </span>
  );
}

/** Kitchen norms per POS item: what one sold unit consumes. */
export function PosItemsPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<PosItem | null>(null);
  const q = useQuery({ queryKey: ["pos-items"], queryFn: () => api<PosItem[]>("/pos-items") });

  const columns = useMemo<ColumnDef<PosItem>[]>(
    () => [
      { id: "name", header: t("sales.posItem"), accessorKey: "name" },
      { id: "code", header: t("sales.code"), accessorKey: "code" },
      {
        id: "norm",
        header: t("sales.norm"),
        enableSorting: false,
        accessorFn: (i) => i.components.map((c) => c.product_name).join(" "),
        cell: ({ row }) => {
          const i = row.original;
          if (i.not_kitchen) return <Badge>{t("sales.notKitchen")}</Badge>;
          if (!i.components.length) return <Badge tone="amber">{t("sales.noNorm")}</Badge>;
          return (
            <ul className="space-y-0.5">
              {i.components.map((c) => (
                <li key={c.product_id}>
                  <NormText c={c} />
                </li>
              ))}
            </ul>
          );
        },
      },
    ],
    [t],
  );

  return (
    <div>
      <PageHeader
        title={t("nav.posItems")}
        actions={
          <Link to="/sales" className="text-sm font-medium text-zinc-700 underline">
            {t("nav.sales")}
          </Link>
        }
      />
      <p className="mb-4 max-w-3xl text-sm text-zinc-600">{t("sales.posItemsExplain")}</p>
      <div className="mb-3 max-w-xs">
        <Input type="search" placeholder={t("common.search")} value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>
      {q.error && <Alert>{errorMessage(q.error, t)}</Alert>}
      <DataTable
        data={q.data}
        columns={columns}
        loading={q.isLoading}
        search={search}
        onRowClick={can("manage_catalog") ? (i) => setEditing(i) : undefined}
        empty={t("sales.noPosItems")}
      />
      {editing && <NormDialog item={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}
