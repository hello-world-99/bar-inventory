import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/auth/AuthContext";
import { Modal } from "@/components/Modal";
import { Alert, Badge, Button, Field, Input } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useDateTime, useMoney, useQty } from "@/lib/format";
import type { StockDocument } from "@/lib/types";
import { uuidv4 } from "@/lib/uuid";

const REVERSIBLE = new Set(["receipt", "write_off", "transfer"]);

function ReverseDialog({ doc, onClose, onDone }: { doc: StockDocument; onClose: () => void; onDone: (rev: StockDocument) => void }) {
  const { t } = useTranslation();
  const [id] = useState(uuidv4); // reused on retry: the server treats the same id as the same request
  const [comment, setComment] = useState("");
  const rev = useMutation({
    mutationFn: (allowNegative: boolean) =>
      api<StockDocument>(`/documents/${doc.id}/reverse`, { method: "POST", body: { id, comment, allow_negative: allowNegative } }),
    onSuccess: onDone,
  });
  const detail = rev.error instanceof ApiError ? rev.error.detail : undefined;
  const canOverride = detail?.code === "insufficient_stock" && detail.can_override;

  return (
    <Modal title={t("docs.reverseTitle")} onClose={onClose}>
      <div className="space-y-4">
        <p className="text-sm text-zinc-600">{t("docs.reverseExplain")}</p>
        {rev.error && <Alert>{errorMessage(rev.error, t)}</Alert>}
        <Field label={t("docs.reverseReason")}>
          <Input value={comment} onChange={(e) => setComment(e.target.value)} maxLength={1000} autoFocus />
        </Field>
        <div className="flex flex-wrap gap-2">
          {canOverride ? (
            <Button variant="danger" disabled={rev.isPending} onClick={() => rev.mutate(true)}>
              {t("docs.reverseNegative")}
            </Button>
          ) : (
            <Button variant="danger" disabled={rev.isPending} onClick={() => rev.mutate(false)}>
              {t("docs.reverse")}
            </Button>
          )}
          <Button variant="secondary" onClick={onClose}>
            {t("common.cancel")}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

export function DocumentView({ id, onClose }: { id: string; onClose: () => void }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const money = useMoney();
  const qty = useQty();
  const dt = useDateTime();
  const [docId, setDocId] = useState(id);
  const [reversing, setReversing] = useState(false);
  const q = useQuery({ queryKey: ["document", docId], queryFn: () => api<StockDocument>(`/documents/${docId}`) });
  const d = q.data;

  return (
    <Modal title={d ? t(`docTypes.${d.type}`) : t("common.loading")} onClose={onClose} wide>
      {!d ? (
        <p className="text-sm text-zinc-500">{q.error ? errorMessage(q.error, t) : t("common.loading")}</p>
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap gap-2">
            {d.reversed_by && <Badge tone="red">{t("docs.reversed")}</Badge>}
            {d.reversal_of && <Badge tone="amber">{t("docs.isReversal")}</Badge>}
            {d.allow_negative && <Badge tone="red">{t("docs.negativeAllowed")}</Badge>}
            {d.backdate_confirmed && <Badge tone="amber">{t("docs.backdated")}</Badge>}
          </div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-xs text-zinc-500">{t("docs.date")}</dt>
              <dd className="font-medium">{dt(d.doc_date)}</dd>
            </div>
            <div>
              <dt className="text-xs text-zinc-500">{t("docs.author")}</dt>
              <dd className="font-medium">{d.created_by_name}</dd>
            </div>
            {d.reason && (
              <div>
                <dt className="text-xs text-zinc-500">{t("docs.reason")}</dt>
                <dd className="font-medium">{t(`reasons.${d.reason}`)}</dd>
              </div>
            )}
            {d.supplier && (
              <div>
                <dt className="text-xs text-zinc-500">{t("docs.supplier")}</dt>
                <dd className="font-medium">{d.supplier}</dd>
              </div>
            )}
            {d.invoice_no && (
              <div>
                <dt className="text-xs text-zinc-500">{t("docs.invoice")}</dt>
                <dd className="font-medium">{d.invoice_no}</dd>
              </div>
            )}
            {d.comment && (
              <div className="col-span-2 sm:col-span-3">
                <dt className="text-xs text-zinc-500">{t("docs.comment")}</dt>
                <dd>{d.comment}</dd>
              </div>
            )}
          </dl>

          <div className="overflow-x-auto rounded-lg border border-zinc-200">
            <table className="w-full min-w-[520px] text-sm">
              <thead className="bg-zinc-50 text-left text-xs uppercase tracking-wide text-zinc-500">
                <tr>
                  <th className="px-3 py-2 font-medium">{t("products.name")}</th>
                  <th className="px-3 py-2 font-medium">{t("docs.location")}</th>
                  <th className="px-3 py-2 text-right font-medium">{t("docs.qty")}</th>
                  <th className="px-3 py-2 text-right font-medium">{t("docs.amount")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {d.lines.map((l) => {
                  const f = qty(l.qty_base, l);
                  const where =
                    l.location_from_name && l.location_to_name
                      ? `${l.location_from_name} → ${l.location_to_name}`
                      : (l.location_to_name ?? l.location_from_name);
                  return (
                    <tr key={l.line_no}>
                      <td className="px-3 py-2">
                        <div className="font-medium">{l.product_name}</div>
                        <div className="text-xs text-zinc-500">
                          {l.product_sku}
                          {l.unit_price && ` · ${money(l.unit_price)} / ${t(`units.short.${l.unit}`)}`}
                        </div>
                      </td>
                      <td className="px-3 py-2">{where}</td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {f.main}
                        {f.alt && <div className="text-xs text-zinc-500">{f.alt}</div>}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{money(l.amount)}</td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr className="bg-zinc-50 font-semibold">
                  <td colSpan={3} className="px-3 py-2">
                    {t("products.total")}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{money(d.total_amount)}</td>
                </tr>
              </tfoot>
            </table>
          </div>

          <div className="flex flex-wrap gap-2">
            {d.reversal_of && (
              <Button variant="secondary" onClick={() => setDocId(d.reversal_of!)}>
                {t("docs.openOriginal")}
              </Button>
            )}
            {d.reversed_by && (
              <Button variant="secondary" onClick={() => setDocId(d.reversed_by!)}>
                {t("docs.openReversal")}
              </Button>
            )}
            {can("reverse_document") && REVERSIBLE.has(d.type) && !d.reversed_by && (
              <Button variant="danger" onClick={() => setReversing(true)}>
                {t("docs.reverse")}
              </Button>
            )}
          </div>
          <p className="text-xs text-zinc-400">
            ID {d.id} · {t("docs.posted")} {d.posted_at ? dt(d.posted_at) : "—"}
          </p>
        </div>
      )}
      {reversing && d && (
        <ReverseDialog
          doc={d}
          onClose={() => setReversing(false)}
          onDone={(rev) => {
            setReversing(false);
            void qc.invalidateQueries();
            setDocId(rev.id);
          }}
        />
      )}
    </Modal>
  );
}

