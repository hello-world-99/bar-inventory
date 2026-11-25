import type { UnitInfo } from "./units";

export type Role = "admin" | "staff";

export type Permission =
  | "view"
  | "manage_catalog"
  | "post_receipt"
  | "post_write_off"
  | "post_transfer"
  | "allow_negative"
  | "backdate"
  | "reverse_document"
  | "inventory_count"
  | "inventory_review"
  | "manage_users"
  | "manage_settings";

export interface User {
  id: number;
  username: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  permissions: Permission[];
}

export interface AppSettings {
  venue_name: string;
  /** display currency; all money is stored in won */
  currency: "KRW" | "USD";
  currency_decimals: number;
  timezone: string;
  business_day_starts_at: string;
  blind_count: boolean;
  usd_krw_rate: string | null;
  rate_mode: "auto" | "manual";
  rate_source: string | null;
  rate_date: string | null;
  rate_updated_at: string | null;
  rate_checked_at: string | null;
  rate_error: string | null;
}

export interface TokenOut {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface Category {
  id: number;
  code: string | null;
  name: string;
  is_active: boolean;
}

export interface Location {
  id: number;
  name: string;
  description: string;
  is_active: boolean;
  product_count: number;
  has_active_inventory: boolean;
}

export interface Product {
  id: number;
  name: string;
  sku: string;
  category_id: number;
  category_code: string | null;
  category_name: string;
  unit: import("./units").Unit;
  base_unit: import("./units").BaseUnit;
  unit_size: string;
  purchase_price: string;
  price_updated_at: string | null;
  min_stock_base: string;
  barcode: string | null;
  full_weight_g: string | null;
  empty_weight_g: string | null;
  is_active: boolean;
  total_qty_base: string;
  stock_value: string;
  is_low_stock: boolean;
  units_locked: boolean;
}

export interface ProductDetail extends Product {
  balances: { location_id: number; location_name: string; location_active: boolean; qty_base: string }[];
}

export interface Page<T> {
  items: T[];
  total: number;
}

export type DocType = "receipt" | "write_off" | "transfer" | "inventory_adjustment" | "reversal";
export type WriteOffReason = "spoilage" | "expired" | "breakage" | "staff_use" | "other" | "sales";
// "sales" is set only by POS sales imports, never offered in the write-off form.
export const WRITE_OFF_REASONS: WriteOffReason[] = ["spoilage", "expired", "breakage", "staff_use", "other"];

export interface DocLine {
  line_no: number;
  product_id: number;
  product_name: string;
  product_sku: string;
  unit: import("./units").Unit;
  base_unit: import("./units").BaseUnit;
  unit_size: string;
  location_from_id: number | null;
  location_from_name: string | null;
  location_to_id: number | null;
  location_to_name: string | null;
  qty_base: string;
  unit_price: string | null;
  unit_cost_base: string | null;
  amount: string;
}

export interface StockDocument {
  id: string;
  type: DocType;
  status: "draft" | "posted";
  doc_date: string;
  reason: WriteOffReason | null;
  supplier: string | null;
  invoice_no: string | null;
  comment: string;
  reversal_of: string | null;
  reversed_by: string | null;
  allow_negative: boolean;
  backdate_confirmed: boolean;
  created_by: number;
  created_by_name: string;
  created_at: string;
  posted_at: string | null;
  inventory_id: number | null;
  total_amount: string;
  lines: DocLine[];
}

export interface DocSummary {
  id: string;
  type: DocType;
  doc_date: string;
  reason: WriteOffReason | null;
  supplier: string | null;
  invoice_no: string | null;
  comment: string;
  reversal_of: string | null;
  reversed_by: string | null;
  created_by_name: string;
  posted_at: string | null;
  line_count: number;
  total_amount: string;
}

export interface Movement {
  id: number;
  document_id: string;
  doc_type: DocType;
  reason: WriteOffReason | null;
  doc_date: string;
  created_at: string;
  product_id: number;
  product_name: string;
  product_sku: string;
  unit: import("./units").Unit;
  base_unit: import("./units").BaseUnit;
  unit_size: string;
  location_id: number;
  location_name: string;
  delta_base: string;
  balance_after: string;
  unit_cost_base: string;
  amount: string;
  user_name: string;
  comment: string;
}

export interface StockRow {
  product_id: number;
  product_name: string;
  product_sku: string;
  category_code: string | null;
  category_name: string;
  unit: import("./units").Unit;
  base_unit: import("./units").BaseUnit;
  unit_size: string;
  location_id: number;
  location_name: string;
  qty_base: string;
  value: string;
  min_stock_base: string;
  /** the product's total is at or below its minimum: shown red */
  is_low_stock: boolean;
}

export type InventoryStatus = "in_progress" | "completed" | "cancelled";

export interface InventoryLine {
  product_id: number;
  product_name: string;
  product_sku: string;
  category_code: string | null;
  category_name: string;
  unit: import("./units").Unit;
  base_unit: import("./units").BaseUnit;
  unit_size: string;
  product_active: boolean;
  counted_base: string | null;
  counted_at: string | null;
  counted_by_name: string | null;
  version: number;
  expected_at_start_base: string | null;
  expected_base: string | null;
  diff_base: string | null;
  unit_cost_base: string | null;
  diff_cost: string | null;
}

export interface Inventory {
  id: number;
  location_id: number;
  location_name: string;
  status: InventoryStatus;
  comment: string;
  started_at: string;
  started_by_name: string;
  closed_at: string | null;
  closed_by_name: string | null;
  adjustment_document_id: string | null;
  line_count: number;
  counted_count: number;
  blind: boolean;
  surplus_cost: string | null;
  shortage_cost: string | null;
  net_cost: string | null;
  lines: InventoryLine[];
}

export interface LowStockItem extends UnitInfo {
  product_id: number;
  name: string;
  sku: string;
  total_qty_base: string;
  min_stock_base: string;
}

export interface LocationValue {
  location_id: number;
  name: string;
  value: string;
  product_count: number;
  is_active: boolean;
}

export interface Dashboard {
  product_count: number;
  location_count: number;
  stock_value: string;
  in_stock_count: number;
  low_stock_count: number;
  negative_count: number;
  by_location: LocationValue[];
  low_stock: LowStockItem[];
  recent_receipts: DocSummary[];
  recent_write_offs: DocSummary[];
  recent_inventories: Inventory[];
}

// ------------------------------------------------------------ POS sales imports
export type SalesImportStatus = "draft" | "posted" | "covered" | "voided";

export interface SalesImportSummary {
  id: string;
  sales_date: string; // YYYY-MM-DD, business day
  status: SalesImportStatus;
  file_name: string;
  total_qty: string;
  total_revenue: string | null;
  location_id: number | null;
  location_name: string | null;
  write_off_id: string | null;
  uploaded_by_name: string;
  uploaded_at: string;
  closed_by_name: string | null;
  closed_at: string | null;
  warning_count: number;
}

export interface UsagePart {
  pos_code: string;
  pos_name: string;
  sold_qty: string;
  per_unit_base: string;
  qty_base: string;
}

export interface UsageItem extends UnitInfo {
  product_id: number;
  product_name: string;
  product_sku: string;
  is_active: boolean;
  qty_base: string;
  unit_cost_base: string;
  amount: string;
  balance_base: string | null;
  min_stock_base: string;
  /** not written off: this completed inventory counted it after the sales (drafts: will be skipped) */
  covered_inventory_id: number | null;
  covered_at: string | null;
  parts: UsagePart[];
}

export interface PosLine {
  pos_item_id: number | null;
  code: string;
  name: string;
  qty: string;
  revenue: string | null;
}

export interface SalesWarning {
  code: "negative_qty" | "total_mismatch" | "file_date_far" | string;
  [k: string]: string;
}

export interface SalesImport extends SalesImportSummary {
  file_sha256: string;
  covered_inventory_id: number | null;
  warnings: SalesWarning[];
  items: UsageItem[];
  unmapped: PosLine[];
  not_kitchen: PosLine[];
  line_count: number;
}

export interface SalesImportList {
  default_sales_date: string;
  items: SalesImportSummary[];
}

export interface PosComponent extends UnitInfo {
  product_id: number;
  product_name: string;
  product_sku: string;
  is_active: boolean;
  qty_base: string;
}

export interface PosItem {
  id: number;
  code: string;
  name: string;
  not_kitchen: boolean;
  components: PosComponent[];
  updated_at: string;
}

export interface PendingDays {
  location_id: number;
  last_imported: string | null;
  days: string[];
  more: number;
}
