import { useQuery } from "@tanstack/react-query";
import Big from "big.js";
import { useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import { useQty } from "@/lib/format";
import type { UnitInfo } from "@/lib/units";

/** Stock of one product at the end of each business day (owner, reply 98). Server: GET /products/{id}/history. */
interface History {
  product_id: number;
  min_stock_base: string;
  days: number;
  points: { day: string; balance: string; qty_in: string; qty_out: string }[];
  places: { location_id: number; location_name: string; balances: string[] }[];
}

const PERIODS = [7, 30, 90] as const;
const H = 220;
const PAD = { top: 12, right: 12, bottom: 26, left: 64 };

/** "Nov 24" for a business day (a plain date: format it in UTC so no zone shifts it). */
function dayLabel(day: string, lang: string, weekday = false) {
  return new Intl.DateTimeFormat(lang, { month: "short", day: "numeric", ...(weekday ? { weekday: "short" } : {}), timeZone: "UTC" }).format(
    new Date(`${day}T00:00:00Z`),
  );
}

/** 1, 2, 5 x 10^n steps: about four gridlines over [0, max]. */
function niceStep(max: number) {
  const raw = max / 4;
  const mag = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
}

function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(600);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(240, Math.floor(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

export function StockChart({ productId, unit }: { productId: number; unit: UnitInfo }) {
  const { t, i18n } = useTranslation();
  const qty = useQty();
  const [days, setDays] = useState<(typeof PERIODS)[number]>(30);
  const [hover, setHover] = useState<number | null>(null);
  const [ref, width] = useWidth();
  const q = useQuery({ queryKey: ["product-history", productId, days], queryFn: () => api<History>(`/products/${productId}/history?days=${days}`) });
  const h = q.data;

  const geo = useMemo(() => {
    if (!h) return null;
    const size = Number(unit.unit_size) || 1; // base units per display unit: ticks fall on whole display units
    const vals = h.points.map((p) => Number(p.balance));
    const min = Number(h.min_stock_base);
    const top = Math.max(...vals, min, 0) / size;
    const step = niceStep(top || 1);
    const yMax = Math.ceil((top || 1) / step) * step * size;
    const plotW = width - PAD.left - PAD.right;
    const plotH = H - PAD.top - PAD.bottom;
    const x = (i: number) => PAD.left + (h.points.length === 1 ? plotW / 2 : (i * plotW) / (h.points.length - 1));
    const y = (v: number) => PAD.top + plotH - (v / yMax) * plotH;
    const ticks = Array.from({ length: Math.round(yMax / (step * size)) + 1 }, (_, i) => i * step * size);
    const every = Math.ceil(h.points.length / Math.max(2, Math.floor(plotW / 70))); // a date label every ~70 px
    return { vals, min, x, y, ticks, every, plotW };
  }, [h, width, unit.unit_size]);

  function onMove(e: PointerEvent<SVGRectElement>) {
    if (!h || !geo) return;
    const box = e.currentTarget.getBoundingClientRect();
    const rel = (e.clientX - box.left) / box.width;
    setHover(Math.max(0, Math.min(h.points.length - 1, Math.round(rel * (h.points.length - 1)))));
  }

  const fmt = (v: string | number) => qty(new Big(v).toString(), unit).main;
  const isLow = (v: number) => geo !== null && (v < 0 || (geo.min > 0 && v <= geo.min));

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{t("history.title")}</h3>
        <div className="inline-flex rounded-lg border border-zinc-200 p-0.5" role="group" aria-label={t("history.period")}>
          {PERIODS.map((d) => (
            <button
              key={d}
              type="button"
              aria-pressed={days === d}
              onClick={() => {
                setDays(d);
                setHover(null);
              }}
              className={`min-h-8 rounded-md px-3 text-xs font-medium ${days === d ? "bg-zinc-900 text-white" : "text-zinc-600 hover:bg-zinc-100"}`}
            >
              {t("history.days", { count: d })}
            </button>
          ))}
        </div>
      </div>

      <div ref={ref} className="relative w-full select-none">
        {!h || !geo ? (
          <div className="flex items-center justify-center text-sm text-zinc-500" style={{ height: H }}>
            {q.isError ? t("common.error") : t("common.loading")}
          </div>
        ) : (
          <>
            <svg width={width} height={H} role="img" aria-label={t("history.aria", { days })} className="block touch-pan-y">
              {/* gridlines and value axis */}
              {geo.ticks.map((v) => (
                <g key={v}>
                  <line x1={PAD.left} x2={width - PAD.right} y1={geo.y(v)} y2={geo.y(v)} stroke="#e4e4e7" strokeWidth={1} />
                  <text x={PAD.left - 8} y={geo.y(v)} dy="0.32em" textAnchor="end" className="fill-zinc-500 text-[11px] tabular-nums">
                    {fmt(v)}
                  </text>
                </g>
              ))}
              {/* date axis */}
              {h.points.map((p, i) =>
                i % geo.every === (h.points.length - 1) % geo.every ? (
                  <text key={p.day} x={geo.x(i)} y={H - 8} textAnchor="middle" className="fill-zinc-500 text-[11px]">
                    {dayLabel(p.day, i18n.language)}
                  </text>
                ) : null,
              )}
              {/* the product's minimum */}
              {geo.min > 0 && (
                <g>
                  <line x1={PAD.left} x2={width - PAD.right} y1={geo.y(geo.min)} y2={geo.y(geo.min)} stroke="#dc2626" strokeWidth={1} strokeDasharray="4 4" />
                  <text x={width - PAD.right} y={geo.y(geo.min) - 4} textAnchor="end" className="fill-red-700 text-[11px]">
                    {t("history.minimum", { qty: fmt(geo.min) })}
                  </text>
                </g>
              )}
              {/* the balance at the end of each business day */}
              <polyline
                points={geo.vals.map((v, i) => `${geo.x(i)},${geo.y(v)}`).join(" ")}
                fill="none"
                stroke="#18181b"
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
              {/* days at or below the minimum */}
              {geo.vals.map((v, i) =>
                isLow(v) ? <circle key={i} cx={geo.x(i)} cy={geo.y(v)} r={4} fill="#dc2626" stroke="#fff" strokeWidth={2} /> : null,
              )}
              {hover !== null && (
                <g pointerEvents="none">
                  <line x1={geo.x(hover)} x2={geo.x(hover)} y1={PAD.top} y2={H - PAD.bottom} stroke="#a1a1aa" strokeWidth={1} />
                  <circle cx={geo.x(hover)} cy={geo.y(geo.vals[hover])} r={5} fill={isLow(geo.vals[hover]) ? "#dc2626" : "#18181b"} stroke="#fff" strokeWidth={2} />
                </g>
              )}
              {/* hit area bigger than the line */}
              <rect
                x={PAD.left}
                y={0}
                width={geo.plotW}
                height={H}
                fill="transparent"
                onPointerMove={onMove}
                onPointerDown={onMove}
                onPointerLeave={() => setHover(null)}
              />
            </svg>
            {hover !== null && (
              <Tooltip
                left={geo.x(hover)}
                width={width}
                title={dayLabel(h.points[hover].day, i18n.language, true)}
                balance={fmt(h.points[hover].balance)}
                low={isLow(geo.vals[hover])}
                qtyIn={new Big(h.points[hover].qty_in).gt(0) ? fmt(h.points[hover].qty_in) : null}
                qtyOut={new Big(h.points[hover].qty_out).gt(0) ? fmt(h.points[hover].qty_out) : null}
                places={h.places.length > 1 ? h.places.map((pl) => [pl.location_name, fmt(pl.balances[hover])] as const) : []}
              />
            )}
          </>
        )}
      </div>

      {h && (
        <details className="mt-2 text-sm">
          <summary className="cursor-pointer text-xs text-zinc-500">{t("history.table")}</summary>
          <div className="mt-2 max-h-64 overflow-auto rounded-lg border border-zinc-200">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-zinc-50 text-left text-zinc-500">
                <tr>
                  <th className="px-3 py-1.5 font-medium">{t("history.day")}</th>
                  <th className="px-3 py-1.5 text-right font-medium">{t("history.in")}</th>
                  <th className="px-3 py-1.5 text-right font-medium">{t("history.out")}</th>
                  <th className="px-3 py-1.5 text-right font-medium">{t("history.balance")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {[...h.points].reverse().map((p) => (
                  <tr key={p.day}>
                    <td className="px-3 py-1.5">{dayLabel(p.day, i18n.language, true)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-emerald-700">{new Big(p.qty_in).gt(0) ? `+${fmt(p.qty_in)}` : ""}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-red-700">{new Big(p.qty_out).gt(0) ? `−${fmt(p.qty_out)}` : ""}</td>
                    <td className={`px-3 py-1.5 text-right tabular-nums ${isLow(Number(p.balance)) ? "font-semibold text-red-700" : ""}`}>{fmt(p.balance)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}

function Tooltip({ left, width, title, balance, low, qtyIn, qtyOut, places }: {
  left: number; width: number; title: string; balance: string; low: boolean; qtyIn: string | null; qtyOut: string | null;
  places: readonly (readonly [string, string])[];
}) {
  const { t } = useTranslation();
  const W = 176;
  const x = Math.min(Math.max(left - W / 2, 0), width - W); // keep it inside the chart
  return (
    <div
      className="pointer-events-none absolute top-0 z-10 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-xs shadow-md"
      style={{ left: x, width: W }}
    >
      <div className="mb-1 font-medium text-zinc-700">{title}</div>
      <div className="flex justify-between gap-2">
        <span className="text-zinc-500">{t("history.balance")}</span>
        <span className={`tabular-nums ${low ? "font-semibold text-red-700" : "font-semibold text-zinc-900"}`}>{balance}</span>
      </div>
      {qtyIn && (
        <div className="flex justify-between gap-2">
          <span className="text-zinc-500">{t("history.in")}</span>
          <span className="tabular-nums text-emerald-700">+{qtyIn}</span>
        </div>
      )}
      {qtyOut && (
        <div className="flex justify-between gap-2">
          <span className="text-zinc-500">{t("history.out")}</span>
          <span className="tabular-nums text-red-700">−{qtyOut}</span>
        </div>
      )}
      {places.map(([name, v]) => (
        <div key={name} className="flex justify-between gap-2 text-zinc-500">
          <span className="truncate">{name}</span>
          <span className="tabular-nums">{v}</span>
        </div>
      ))}
    </div>
  );
}
