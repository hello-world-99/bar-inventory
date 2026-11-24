import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type FilterFn,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { cn } from "./ui";

export interface DataTableProps<T> {
  data: T[] | undefined;
  columns: ColumnDef<T, any>[]; // eslint-disable-line @typescript-eslint/no-explicit-any
  loading?: boolean;
  /** text used by the search box; defaults to every string cell */
  search?: string;
  searchText?: (row: T) => string;
  initialSort?: SortingState;
  onRowClick?: (row: T) => void;
  rowClassName?: (row: T) => string | undefined;
  empty?: ReactNode;
  minWidth?: number;
}

/** Client-side table with sorting and search; fine for a single bar's catalog (hundreds of rows). */
export function DataTable<T>({
  data,
  columns,
  loading,
  search = "",
  searchText,
  initialSort = [],
  onRowClick,
  rowClassName,
  empty,
  minWidth = 640,
}: DataTableProps<T>) {
  const { t } = useTranslation();
  const [sorting, setSorting] = useState<SortingState>(initialSort);

  const globalFilter: FilterFn<T> = (row, _col, value: string) => {
    const hay = searchText ? searchText(row.original) : JSON.stringify(row.original);
    return hay.toLowerCase().includes(value.trim().toLowerCase());
  };

  const table = useReactTable({
    data: data ?? [],
    columns,
    state: { sorting, globalFilter: search },
    onSortingChange: setSorting,
    globalFilterFn: globalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  const rows = table.getRowModel().rows;

  return (
    <div className="overflow-x-auto rounded-xl border border-zinc-200 bg-white">
      <table className="w-full text-sm" style={{ minWidth }}>
        <thead className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500">
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id}>
              {hg.headers.map((h) => {
                const sortable = h.column.getCanSort();
                const dir = h.column.getIsSorted();
                const align = (h.column.columnDef.meta as { align?: string } | undefined)?.align;
                return (
                  <th key={h.id} className={cn("px-4 py-3 font-medium", align === "right" && "text-right")}>
                    {sortable ? (
                      <button
                        type="button"
                        onClick={h.column.getToggleSortingHandler()}
                        className={cn("inline-flex items-center gap-1 uppercase hover:text-zinc-900", align === "right" && "flex-row-reverse")}
                      >
                        {flexRender(h.column.columnDef.header, h.getContext())}
                        {dir === "asc" ? <ArrowUp className="h-3 w-3" /> : dir === "desc" ? <ArrowDown className="h-3 w-3" /> : <ArrowUpDown className="h-3 w-3 opacity-40" />}
                      </button>
                    ) : (
                      flexRender(h.column.columnDef.header, h.getContext())
                    )}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody className="divide-y divide-zinc-100">
          {loading && (
            <tr>
              <td colSpan={columns.length} className="px-4 py-8 text-center text-zinc-500">
                {t("common.loading")}
              </td>
            </tr>
          )}
          {!loading && rows.length === 0 && (
            <tr>
              <td colSpan={columns.length} className="px-4 py-8 text-center text-zinc-500">
                {empty ?? t("common.noResults")}
              </td>
            </tr>
          )}
          {rows.map((r) => (
            <tr
              key={r.id}
              onClick={onRowClick ? () => onRowClick(r.original) : undefined}
              className={cn(onRowClick && "cursor-pointer hover:bg-zinc-50", rowClassName?.(r.original))}
            >
              {r.getVisibleCells().map((c) => {
                const align = (c.column.columnDef.meta as { align?: string } | undefined)?.align;
                return (
                  <td key={c.id} className={cn("px-4 py-3 align-top", align === "right" && "text-right tabular-nums")}>
                    {flexRender(c.column.columnDef.cell, c.getContext())}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
