import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Big from "big.js";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { BalanceText } from "@/components/BalanceText";
import { Modal } from "@/components/Modal";
import { Alert, Badge, Button, Field, Input } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useDateTime, useQty } from "@/lib/format";
import type { StockDocument, DocLine } from "@/lib/types";
import { uuidv4 } from "@/lib/uuid";

const REVERSIBLE = new Set(["receipt", "write_off", "transfer"]);

function ReverseDialog({ doc, onClose, onDone }: { doc: StockDocument; onClose: () => void; onDone: (rev: StockDocument) => void }) {
  const { t } = useTranslation();
  const [id] = useState(uuidv4); // reused on retry: the server treats the same id as the same request
  const [comment, setComment] = useState("");
  const rev = useMutation({
    mutationFn: () => api<StockDocument>(`/documents/${doc.id}/reverse`, { method: "POST", body: { id, comment } }),
    onSuccess: onDone,
  });

  return (
    <Modal title={t("docs.reverseTitle")} onClose={onClose}>
      <div className="space-y-4">
        <p className="text-sm text-zinc-600">{t("docs.reverseExplain")}</p>
        {rev.error && <Alert>{errorMessage(rev.error, t)}</Alert>}
        <Field label={t("docs.reverseReason")}>
          <Input value={comment} onChange={(e) => setComment(e.target.value)} maxLength={1000} autoFocus />
        </Field>
        <div className="flex flex-wrap gap-2">
          <Button variant="danger" disabled={rev.isPending} onClick={() => rev.mutate()}>
            {t("docs.reverse")}
          </Button>
          <Button variant="secondary" onClick={onClose}>
            {t("common.cancel")}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

/** How much there was at each place right before this line (owner: "how much there was before the change").
 * The source side lost |qty|, the destination gained it: before = after -/+ |qty|. */
function BeforeCell({ line }: { line: DocLine }) {
  const q = new Big(line.qty_base).abs();
  const both = line.balance_after_from !== null && line.balance_after_to !== null;
  if (line.balance_after_from === null && line.balance_after_to === null) return <span className="text-zinc-400">—</span>;
  return (
    <span className="tabular-nums">
      {line.balance_after_from !== null && (
        <span className="block">
          {both && `${line.location_from_name}: `}
          <BalanceText qtyBase={new Big(line.balance_after_from).plus(q).toString()} unit={line} />
        </span>
      )}
      {line.balance_after_to !== null && (
        <span className="block">
          {both && `${line.location_to_name}: `}
          <BalanceText qtyBase={new Big(line.balance_after_to).minus(q).toString()} unit={line} />
        </span>
      )}
    </span>
  );
}

export function DocumentView({ id, onClose }: { id: string; onClose: () => void }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
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
            {d.backdate_confirmed && <Badge tone="amber">{t("docs.backdated")}</Badge>}
            {d.sales_import_id && (
              <Link className="text-sm underline" to={`/sales/${d.sales_import_id}`} onClick={onClose}>
                {d.type === "inventory_adjustment" ? t("docs.posCompensation") : t("docs.posReport")}
              </Link>
            )}
          </div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-xs text-zinc-500">{t("docs.date")}</dt>
              <dd className="font-medium">{dt(d.doc_date)}</dd>
            </div>
            <div>
              <dt className="text-xs text-zinc-500">{t("docs.author")}</dt>
              <dd className="font-medium">
                {d.created_by_name}
                {d.entered_by_name && d.entered_by_name !== d.created_by_name && (
                  <div className="text-xs font-normal text-zinc-500">{t("docs.enteredBy", { name: d.entered_by_name })}</div>
                )}
              </dd>
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
                  <th className="px-3 py-2 text-right font-medium">{t("docs.before")}</th>
                  <th className="px-3 py-2 text-right font-medium">{t("journal.change")}</th>
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
                        </div>
                      </td>
                      <td className="px-3 py-2">{where}</td>
                      <td className="px-3 py-2 text-right">
                        <BeforeCell line={l} />
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {/* signed change (owner: "+ when added, − when taken away"), per place; after it the balance */}
                        {[
                          { place: l.location_from_name, sign: "−", tone: "text-red-700", after: l.balance_after_from },
                          { place: l.location_to_name, sign: "+", tone: "text-emerald-700", after: l.balance_after_to },
                        ]
                          .filter((x) => x.place)
                          .map((x, _i, all) => (
                            <div key={x.sign}>
                              {all.length > 1 && <span className="text-xs text-zinc-500">{x.place}: </span>}
                              <span className={`font-medium ${x.tone}`}>
                                {x.sign}
                                {f.main.replace(/^−/, "")}
                              </span>
                              {x.after !== null && (
                                <span className="text-xs text-zinc-500">
                                  {" "}
                                  → <BalanceText qtyBase={x.after} unit={l} />
                                </span>
                              )}
                            </div>
                          ))}
                        {f.alt && <div className="text-xs text-zinc-500">{f.alt.replace(/^−/, "")}</div>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
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
            {/* a POS write-off is corrected or voided on its report (reply 50) */}
            {can("reverse_document") && REVERSIBLE.has(d.type) && !d.reversed_by && d.reason !== "sales" && (
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

