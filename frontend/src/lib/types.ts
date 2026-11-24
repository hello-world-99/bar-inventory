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
  currency: string;
  currency_decimals: number;
  timezone: string;
  business_day_starts_at: string;
  blind_count: boolean;
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
export type WriteOffReason = "spoilage" | "expired" | "breakage" | "staff_use" | "other";
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
