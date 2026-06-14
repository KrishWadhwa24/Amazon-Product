/**
 * Catalog types and shared formatting helpers for the buyer-facing surfaces
 * (home/catalog grid, product detail, and cart).
 *
 * The `Product` shape mirrors the backend `GET /api/products` /
 * `GET /api/products/{asin}` representation (built in task 20.2):
 * `{ id, asin, name, price, rating, review_count, image_url, uploaded_image_path }`.
 */

/** A catalog product as returned by the products endpoints. */
export interface Product {
  id: number;
  asin: string;
  name: string;
  /** Price in INR (₹). */
  price: number;
  /** Average rating in [0.0, 5.0]. */
  rating: number;
  /** Number of reviews (integer >= 0). */
  review_count: number;
  /** Official catalog image URL (NOT NULL on the backend). */
  image_url: string;
  /** Local path of an uploaded photo, or null until one is uploaded. */
  uploaded_image_path: string | null;
}

/** Product fields surfaced alongside a cart item by `GET /api/cart`. */
export interface CartItemProduct {
  asin: string;
  name: string;
  /** Price in INR (₹). */
  price: number;
  image_url: string;
  uploaded_image_path: string | null;
}

/**
 * A single cart line item as returned by `GET /api/cart` (task 20.2).
 *
 * The backend nests the product under `product` (CartItemResource):
 * `{ id, product_id, added_at, unit_price, resale_listing_id, condition_grade,
 *    condition_image_url, product: { asin, name, price, image_url, uploaded_image_path } }`.
 *
 * `unit_price` is the price charged for the line — the catalog price for an
 * ordinary item, or the discounted resale price for an open-box resale line
 * (in which case `resale_listing_id` and the condition fields are set). Numeric
 * fields may arrive as numbers or numeric strings (backend Decimal
 * serialization); consumers coerce with `Number(...)` before arithmetic.
 */
export interface CartItem {
  id: number;
  product_id: number;
  added_at: string;
  unit_price?: number | string | null;
  resale_listing_id?: number | null;
  condition_grade?: string | null;
  condition_image_url?: string | null;
  product: CartItemProduct;
}

/**
 * The effective unit price of a cart line, coerced to a finite number. Prefers
 * the line's `unit_price` (resale or catalog), falling back to the product
 * price. Backend Decimal values may arrive as strings, so this always coerces.
 */
export function cartLinePrice(item: CartItem): number {
  const raw = item.unit_price ?? item.product.price;
  const n = typeof raw === "string" ? Number(raw) : raw;
  return Number.isFinite(n) ? (n as number) : 0;
}

/** Shared ₹ INR currency formatter (2 decimal places). */
export const inr = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 2,
});

/**
 * Prefer an uploaded photo, then the official catalog image. Returns null when
 * neither is usable so {@link ProductImage} falls back to its placeholder.
 */
export function productImageSrc(p: {
  image_url?: string | null;
  uploaded_image_path?: string | null;
}): string | null {
  return p.uploaded_image_path || p.image_url || null;
}
