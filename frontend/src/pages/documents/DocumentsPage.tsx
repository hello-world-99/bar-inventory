import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/auth/AuthContext";
import { DataTable } from "@/components/DataTable";
import { Modal } from "@/components/Modal";
import { Alert, Badge, Button, Input, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useDateTime, useMoney } from "@/lib/format";
import type { DocSummary, DocType, Page, Permission, StockDocument } from "@/lib/types";
import { DocumentView } from "./DocumentView";
import { ReceiptForm, TransferForm, WriteOffForm } from "./forms";

const CONFIG: Record<"receipt" | "write_off" | "transfer", { title: string; perm: Permission; newKey: string }> = {
  receipt: { title: "nav.receipts", perm: "post_receipt", newKey: "docs.newReceipt" },
  write_off: { title: "nav.writeOffs", perm: "post_write_off", newKey: "docs.newWriteOff" },
  transfer: { title: "nav.transfers", perm: "post_transfer", newKey: "docs.newTransfer" },
};

export function DocumentsPage({ type }: { type: "receipt" | "write_off" | "transfer" }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const money = useMoney();
  const dt = useDateTime();
  const cfg = CONFIG[type];
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [creating, setCreating] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);

  const params = new URLSearchParams({ type, limit: "500", ...(from ? { date_from: from } : {}), ...(to ? { date_to: to } : {}) });
  const docs = useQuery({ queryKey: ["documents", params.toString()], queryFn: () => api<Page<DocSummary>>(`/documents?${params}`) });

  const columns = useMemo<ColumnDef<DocSummary, unknown>[]>(() => {
    const cols: ColumnDef<DocSummary, unknown>[] = [
      { id: "date", header: t("docs.date"), accessorFn: (d) => d.doc_date, cell: ({ row: { original: d } }) => (
        <div>
          <div>{dt(d.doc_date)}</div>
          {d.reversed_by && <Badge tone="red">{t("docs.reversed")}</Badge>}
        </div>
      ) },
    ];
    if (type === "receipt")
      cols.push({ id: "supplier", header: t("docs.supplier"), accessorFn: (d) => `${d.supplier ?? ""} ${d.invoice_no ?? ""}`, cell: ({ row: { original: d } }) => (
        <div>
          <div>{d.supplier ?? "—"}</div>
          {d.invoice_no && <div className="text-xs text-zinc-500">#{d.invoice_no}</div>}
        </div>
      ) });
    if (type === "write_off") cols.push({ id: "reason", header: t("docs.reason"), accessorFn: (d) => (d.reason ? t(`reasons.${d.reason}`) : "") });
    cols.push(
      { id: "comment", header: t("docs.comment"), accessorFn: (d) => d.comment, cell: ({ getValue }) => <span className="line-clamp-2">{getValue() as string}</span> },
      { id: "lines", header: t("docs.lines"), meta: { align: "right" }, accessorFn: (d) => d.line_count },
      { id: "author", header: t("docs.author"), accessorFn: (d) => d.created_by_name },
    );
    return cols;
  }, [t, dt, money, type]);

  const Form = type === "receipt" ? ReceiptForm : type === "write_off" ? WriteOffForm : TransferForm;

  return (
    <>
      <PageHeader title={t(cfg.title)} actions={can(cfg.perm) && <Button onClick={() => setCreating(true)}>{t(cfg.newKey)}</Button>} />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <label className="text-sm">
          <span className="mb-1 block text-zinc-600">{t("docs.dateFrom")}</span>
          <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-zinc-600">{t("docs.dateTo")}</span>
          <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
      </div>
      {docs.error && (
        <div className="mb-4">
          <Alert>{errorMessage(docs.error, t)}</Alert>
        </div>
      )}
      <DataTable data={docs.data?.items} columns={columns} loading={docs.isLoading} initialSort={[{ id: "date", desc: true }]} onRowClick={(d) => setOpenId(d.id)} empty={t("docs.empty")} />
      {creating && (
        <Modal title={t(cfg.newKey)} onClose={() => setCreating(false)} wide>
          <Form
            onCancel={() => setCreating(false)}
            onDone={(d: StockDocument) => {
              setCreating(false);
              setOpenId(d.id);
            }}
          />
        </Modal>
      )}
      {openId && <DocumentView id={openId} onClose={() => setOpenId(null)} />}
    </>
  );
}

export type { DocType };
