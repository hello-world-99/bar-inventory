import { useMutation, useQueryClient } from "@tanstack/react-query";
import Big from "big.js";
import { Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/Modal";
import { ProductPicker, QtyField, useActiveProducts } from "@/components/pickers";
import { Alert, Button } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { PosItem } from "@/lib/types";
import { plain, type Unit } from "@/lib/units";
import { uuidv4 } from "@/lib/uuid";

interface Row {
  key: string;
  product_id: number | null;
  qty: string;
  qty_unit: Unit | null;
}

/** Norms confirmed by the owner for dishes not yet seen in the POS (reply 32): offered as one-click presets. */
const PRESETS: { key: string; parts: { sku: string; qty: string; unit: Unit }[] }[] = [
  { key: "burger", parts: [{ sku: "KIT-FRIES", qty: "175", unit: "g" }, { sku: "KIT-BURGER-MEAT", qty: "200", unit: "g" }, { sku: "KIT-BURGER-BUN", qty: "1", unit: "pcs" }] },
];

/** What one sold unit of a POS item consumes. `item` may come from a report (only id/code/name known). */
export function NormDialog({ item, onClose }: { item: Pick<PosItem, "id" | "code" | "name"> & Partial<PosItem>; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const products = useActiveProducts().data ?? [];
  const [notKitchen, setNotKitchen] = useState(item.not_kitchen ?? false);
  const [rows, setRows] = useState<Row[]>(() =>
    (item.components ?? []).map((c) => {
      return { key: uuidv4(), product_id: c.product_id, qty: plain(new Big(c.qty_base)), qty_unit: c.base_unit }; // norms are small: base unit
    }),
  );
  const save = useMutation({
    mutationFn: () =>
      api<PosItem>(`/pos-items/${item.id}`, {
        method: "PUT",
        body: {
          not_kitchen: notKitchen,
          components: notKitchen ? [] : rows.filter((r) => r.product_id && r.qty).map((r) => ({ product_id: r.product_id, qty: r.qty, qty_unit: r.qty_unit })),
        },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["pos-items"] });
      void qc.invalidateQueries({ queryKey: ["sales-import"] });
      onClose();
    },
  });
  const presets = PRESETS.filter((p) => p.parts.every((x) => products.some((pr) => pr.sku === x.sku)));
  const applyPreset = (key: string) => {
    const preset = PRESETS.find((p) => p.key === key)!;
    setRows(preset.parts.map((x) => ({ key: uuidv4(), product_id: products.find((p) => p.sku === x.sku)!.id, qty: x.qty, qty_unit: x.unit })));
    setNotKitchen(false);
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };

  return (
    <Modal title={t("sales.normTitle", { name: item.name, code: item.code })} onClose={onClose} wide>
      <form onSubmit={submit} className="space-y-4 text-sm">
        <p className="text-zinc-600">{t("sales.normExplain")}</p>
        <label className="flex items-center gap-2">
          <input type="checkbox" className="h-4 w-4" checked={notKitchen} onChange={(e) => setNotKitchen(e.target.checked)} />
          {t("sales.notKitchenLabel")}
        </label>
        {!notKitchen && (
          <div className="space-y-2">
            {rows.map((r, i) => {
              const p = products.find((x) => x.id === r.product_id) ?? null;
              return (
                <div key={r.key} className="grid gap-2 rounded-lg border border-zinc-200 p-2 sm:grid-cols-12 sm:items-center">
                  <div className="sm:col-span-6">
                    <ProductPicker products={products} value={r.product_id} onChange={(np) => setRows(rows.map((x, j) => (j === i ? { ...x, product_id: np.id, qty_unit: np.base_unit } : x)))} />
                  </div>
                  <div className="sm:col-span-5">
                    <QtyField product={p} qty={r.qty} unit={r.qty_unit} onChange={(qty, unit) => setRows(rows.map((x, j) => (j === i ? { ...x, qty, qty_unit: unit } : x)))} />
                  </div>
                  <button type="button" aria-label={t("common.delete")} onClick={() => setRows(rows.filter((_, j) => j !== i))} className="justify-self-end rounded-lg p-2 text-zinc-500 hover:bg-zinc-100 sm:col-span-1">
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              );
            })}
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="secondary" onClick={() => setRows([...rows, { key: uuidv4(), product_id: null, qty: "", qty_unit: null }])}>
                <Plus className="h-4 w-4" /> {t("sales.addComponent")}
              </Button>
              {presets.map((p) => (
                <Button key={p.key} type="button" variant="secondary" onClick={() => applyPreset(p.key)}>
                  {t(`sales.preset.${p.key}`)}
                </Button>
              ))}
            </div>
          </div>
        )}
        {save.error && <Alert>{errorMessage(save.error, t)}</Alert>}
        <div className="flex gap-2">
          <Button type="submit" disabled={save.isPending}>
            {t("common.save")}
          </Button>
          <Button type="button" variant="secondary" onClick={onClose}>
            {t("common.cancel")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
