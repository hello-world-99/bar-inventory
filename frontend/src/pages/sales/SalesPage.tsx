import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Upload } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { DataTable } from "@/components/DataTable";
import { Alert, Button, Card, Field, Input, PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useDateTime } from "@/lib/format";
import type { SalesImport, SalesImportList, SalesImportSummary } from "@/lib/types";
import { uuidv4 } from "@/lib/uuid";
import { StatusBadge } from "./SalesReportPage";

const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

function UploadCard({ defaultDate }: { defaultDate: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [day, setDay] = useState(defaultDate);
  const { user } = useAuth();
  const [preparedBy, setPreparedBy] = useState(user?.full_name || user?.username || "");
  const [id, setId] = useState(uuidv4); // one id per chosen file+date: a retry after a lost response is the same upload
  useEffect(() => setDay((d) => d || defaultDate), [defaultDate]);

  const up = useMutation({
    mutationFn: () =>
      api<SalesImport>(`/sales-imports?${new URLSearchParams({ id, sales_date: day, file_name: file!.name, prepared_by: preparedBy.trim() })}`, {
        method: "POST",
        body: file!,
        headers: { "Content-Type": XLSX },
      }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["sales-imports"] });
      navigate(`/sales/${r.id}`);
    },
  });
  const detail = up.error instanceof ApiError ? up.error.detail : undefined;
  const existing = typeof detail?.import_id === "string" ? detail.import_id : null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (file && day) up.mutate();
  };
  return (
    <Card className="mb-6 p-4">
      {/* One row on wide screens; every field is "label + control" with no hint, so the controls line up (hints below). */}
      <form onSubmit={submit} className="grid items-end gap-4 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_12rem_11rem_auto]">
        <div className="space-y-1.5">
          <span className="block text-sm font-medium text-zinc-700">{t("sales.file")}</span>
          {/* The browser's own file input is labelled in the OS language; this one is always English. */}
          <label className="flex h-10 w-full cursor-pointer items-center gap-3 rounded-lg border border-zinc-300 bg-white px-1.5 text-sm hover:bg-zinc-50 focus-within:border-zinc-900 focus-within:ring-1 focus-within:ring-zinc-900">
            <input
              type="file"
              className="sr-only"
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null);
                setId(uuidv4());
                up.reset();
              }}
            />
            <span className="shrink-0 rounded-md bg-zinc-100 px-2.5 py-1 font-medium text-zinc-800">{t("sales.chooseFile")}</span>
            <span className={file ? "min-w-0 truncate text-zinc-800" : "min-w-0 truncate text-zinc-500"}>{file ? file.name : t("sales.noFileChosen")}</span>
          </label>
        </div>
        <Field label={t("sales.preparedBy")}>
          <Input className="h-10" value={preparedBy} maxLength={100} onChange={(e) => setPreparedBy(e.target.value)} />
        </Field>
        <Field label={t("sales.salesDate")}>
          <Input
            className="h-10"
            type="date"
            value={day}
            onChange={(e) => {
              setDay(e.target.value);
              setId(uuidv4());
              up.reset();
            }}
            required
          />
        </Field>
        <Button type="submit" className="h-10" disabled={!file || !day || up.isPending}>
          <Upload className="h-4 w-4" /> {up.isPending ? t("common.loading") : t("sales.upload")}
        </Button>
      </form>
      <p className="mt-2 text-xs text-zinc-500">
        {t("sales.fileHint")}. {t("sales.preparedByHint")}. {t("sales.dateHint")}
      </p>
      {up.error && (
        <div className="mt-3">
          <Alert>
            {errorMessage(up.error, t)}
            {existing && (
              <>
                {" "}
                <Link className="font-medium underline" to={`/sales/${existing}`}>
                  {t("sales.openExisting")}
                </Link>
              </>
            )}
          </Alert>
        </div>
      )}
    </Card>
  );
}

export function SalesPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const navigate = useNavigate();
  const dt = useDateTime();
  const list = useQuery({ queryKey: ["sales-imports"], queryFn: () => api<SalesImportList>("/sales-imports") });

  const columns = useMemo<ColumnDef<SalesImportSummary>[]>(
    () => [
      { id: "date", header: t("sales.salesDate"), accessorKey: "sales_date" },
      { id: "status", header: t("sales.status"), accessorKey: "status", cell: ({ row }) => <StatusBadge status={row.original.status} /> },
      { id: "location", header: t("docs.location"), accessorFn: (r) => r.location_name ?? "" },
      { id: "file", header: t("sales.file"), accessorKey: "file_name" },
      { id: "items", header: t("sales.itemsSold"), accessorFn: (r) => Number(r.total_qty) },
      { id: "prepared", header: t("sales.preparedBy"), accessorFn: (r) => r.prepared_by ?? "" },
      { id: "by", header: t("sales.uploadedBy"), accessorFn: (r) => `${r.uploaded_by_name} · ${dt(r.uploaded_at)}` },
    ],
    [t, dt],
  );

  return (
    <div>
      <PageHeader
        title={t("nav.sales")}
        actions={
          <Link to="/pos-items" className="text-sm font-medium text-zinc-700 underline">
            {t("nav.posItems")}
          </Link>
        }
      />
      <p className="mb-4 max-w-3xl text-sm text-zinc-600">{t("sales.explain")}</p>
      {can("post_write_off") && list.data && <UploadCard defaultDate={list.data.default_sales_date} />}
      {list.error && <Alert>{errorMessage(list.error, t)}</Alert>}
      <DataTable
        data={list.data?.items}
        columns={columns}
        loading={list.isLoading}
        initialSort={[{ id: "date", desc: true }]}
        onRowClick={(r) => navigate(`/sales/${r.id}`)}
        rowClassName={(r) => (r.status === "voided" ? "text-zinc-400" : undefined)}
        empty={t("sales.none")}
      />
    </div>
  );
}
