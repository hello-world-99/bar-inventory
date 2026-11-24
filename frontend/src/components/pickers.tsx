import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import type { Location, Page, Product } from "@/lib/types";
import { inputUnits, type Unit } from "@/lib/units";
import { cn, Input, Select } from "./ui";

export function useActiveProducts() {
  return useQuery({
    queryKey: ["products", "picker"],
    queryFn: () => api<Page<Product>>("/products?active=active&limit=1000"),
    select: (d) => d.items,
  });
}

export function useActiveLocations() {
  return useQuery({ queryKey: ["locations", "active"], queryFn: () => api<Location[]>("/locations?active=active") });
}

/** Search-as-you-type product chooser (name, SKU or exact barcode). Works with a scanner that types + Enter. */
export function ProductPicker({
  products,
  value,
  onChange,
  autoFocus,
}: {
  products: Product[];
  value: number | null;
  onChange: (p: Product) => void;
  autoFocus?: boolean;
}) {
  const { t } = useTranslation();
  const selected = products.find((p) => p.id === value) ?? null;
  const [text, setText] = useState(selected ? selected.name : "");
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => setText(selected ? selected.name : ""), [selected]);

  const matches = useMemo(() => {
    const q = text.trim().toLowerCase();
    if (!q || (selected && text === selected.name)) return products.slice(0, 8);
    const exact = products.filter((p) => p.barcode === text.trim());
    if (exact.length) return exact;
    return products.filter((p) => p.name.toLowerCase().includes(q) || p.sku.toLowerCase().includes(q)).slice(0, 8);
  }, [products, text, selected]);

  useEffect(() => {
    const close = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  function pick(p: Product) {
    onChange(p);
    setText(p.name);
    setOpen(false);
  }

  return (
    <div ref={box} className="relative">
      <Input
        value={text}
        autoFocus={autoFocus}
        placeholder={t("docs.pickProduct")}
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
          setHi(0);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") setHi((h) => Math.min(h + 1, matches.length - 1));
          else if (e.key === "ArrowUp") setHi((h) => Math.max(h - 1, 0));
          else if (e.key === "Enter" && open && matches[hi]) {
            e.preventDefault();
            pick(matches[hi]);
          } else if (e.key === "Escape") setOpen(false);
        }}
        aria-autocomplete="list"
        role="combobox"
        aria-expanded={open}
      />
      {open && matches.length > 0 && (
        <ul role="listbox" className="absolute z-50 mt-1 max-h-64 w-full overflow-auto rounded-lg border border-zinc-200 bg-white py-1 shadow-lg">
          {matches.map((p, i) => (
            <li
              key={p.id}
              role="option"
              aria-selected={p.id === value}
              onMouseDown={(e) => {
                e.preventDefault();
                pick(p);
              }}
              className={cn("cursor-pointer px-3 py-2 text-sm", i === hi ? "bg-zinc-100" : "hover:bg-zinc-50")}
            >
              <span className="font-medium">{p.name}</span> <span className="text-xs text-zinc-500">{p.sku}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function LocationSelect({
  locations,
  value,
  onChange,
  placeholder,
  exclude,
}: {
  locations: Location[];
  value: number | null;
  onChange: (id: number) => void;
  placeholder?: string;
  exclude?: number | null;
}) {
  const { t } = useTranslation();
  return (
    <Select value={value ?? ""} onChange={(e) => onChange(Number(e.target.value))} required>
      <option value="" disabled>
        {placeholder ?? t("docs.pickLocation")}
      </option>
      {locations
        .filter((l) => l.id !== exclude)
        .map((l) => (
          <option key={l.id} value={l.id}>
            {l.name}
          </option>
        ))}
    </Select>
  );
}

/** Quantity plus the unit it is entered in (product unit, base unit or metric unit of the same base). */
export function QtyField({
  product,
  qty,
  unit,
  onChange,
}: {
  product: Product | null;
  qty: string;
  unit: Unit | null;
  onChange: (qty: string, unit: Unit) => void;
}) {
  const { t } = useTranslation();
  const units = product ? inputUnits(product) : [];
  const u = unit ?? product?.unit ?? null;
  return (
    <div className="flex gap-2">
      <Input
        inputMode="decimal"
        value={qty}
        placeholder="0"
        onChange={(e) => onChange(e.target.value.replace(",", "."), u ?? "pcs")}
        required
        className="min-w-0 flex-1"
      />
      <Select value={u ?? ""} disabled={!product || units.length < 2} onChange={(e) => onChange(qty, e.target.value as Unit)} className="w-24 shrink-0">
        {units.map((x) => (
          <option key={x} value={x}>
            {t(`units.short.${x}`)}
          </option>
        ))}
      </Select>
    </div>
  );
}
