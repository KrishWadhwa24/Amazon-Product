/**
 * Match-notification types and fetch helper for the buyer-facing match popup
 * (Requirements 7.4, 8.1, 8.2, 8.3).
 *
 * The shape mirrors the backend `GET /api/notifications` representation
 * (task 21.1): each entry is a PENDING MatchCandidate for the active buyer,
 * enriched with the deal headline and cached impact. `carbon_avoided_kg` is
 * omitted by the backend when the avoided carbon is below 0.1 kg
 * (Requirement 7.3), so it is optional/nullable here.
 */

import { api } from "@/lib/api";

/**
 * The Flow 18 deal headline (Requirement 1.8 / Requirement 8.2). The popup
 * prefers the backend-provided `headline`, falling back to this constant when
 * the field is absent so the demo copy is always present.
 */
export const LOCAL_DEAL_HEADLINE = "🔥 Local Open-Box Deal Found Near You";

/** Supporting line shown beneath the headline (Requirement 8.2). */
export const LOCAL_DEAL_SUBHEADLINE =
  "A verified customer nearby is returning this exact item.";

/** Product fields surfaced alongside a match notification. */
export interface NotificationProduct {
  name: string;
  asin: string;
  image_url: string;
  uploaded_image_path: string | null;
}

/**
 * A single PENDING match notification for the active buyer.
 *
 * Numeric fields may arrive as numbers or as numeric strings (backend Decimal
 * serialization); consumers coerce with `Number(...)` before formatting.
 */
export interface MatchNotification {
  /** MatchCandidate id; used for `POST /api/matches/{candidate_id}/(accept|reject)`. */
  candidate_id: number;
  /** Deal headline (e.g. {@link LOCAL_DEAL_HEADLINE}). */
  headline: string;
  /** Money saved (₹), equal to the Local_Discount (Requirement 7.2). */
  money_saved: number | string;
  /** Whole hours of delivery time saved, >= 0 (Requirement 7.2). */
  delivery_time_saved_hours: number;
  /** Carbon avoided in kg CO2; omitted/null when < 0.1 kg (Requirement 7.3). */
  carbon_avoided_kg?: number | null;
  /** Distance to the returning seller in km. */
  distance_km: number | string;
  /** The matched product. */
  product: NotificationProduct;
}

/**
 * Fetch the active buyer's PENDING match notifications from
 * `GET /api/notifications` (Requirement 8.1). Always resolves to an array;
 * a non-array payload is normalized to an empty list.
 */
export async function fetchNotifications(): Promise<MatchNotification[]> {
  const data = await api.get<MatchNotification[]>("/api/notifications");
  return Array.isArray(data) ? data : [];
}
