"use client";

/**
 * Match notification popup (Requirements 7.4, 8.2, 8.3, 8.4, 8.5).
 *
 * Presentational Amazon-styled toast/card shown when a PENDING MatchCandidate
 * exists for the active buyer. It renders the deal headline, the supporting
 * "verified customer nearby" line, the money saved (₹), the delivery time
 * saved, and — only when present (Requirement 7.3) — the carbon avoided, plus
 * the matched product (image + name).
 *
 * Two actions are always enabled and visible (Requirements 7.4, 8.2):
 *  - "Claim Deal"            → `onClaim`        (accept the match)
 *  - "Keep Original Delivery" → `onKeepOriginal` (reject the match)
 *
 * This component is purely presentational: hiding the popup within 1s on either
 * action (Requirements 8.4, 8.5) and the accept/reject network calls are owned
 * by {@link NotificationPoller}. While no notification exists the poller renders
 * nothing (Requirement 8.3), so this component always receives a notification.
 */

import { MapPin, Leaf, Clock, Sparkles, X } from "lucide-react";

import { PrimaryButton } from "@/components/PrimaryButton";
import { ProductImage } from "@/components/ProductImage";
import { inr, productImageSrc } from "@/lib/catalog";
import { CLAIMED_DEAL_DISCOUNT } from "@/lib/localOrders";
import {
  LOCAL_DEAL_HEADLINE,
  LOCAL_DEAL_SUBHEADLINE,
  type MatchNotification,
} from "@/lib/notifications";

export interface MatchNotificationPopupProps {
  /** The PENDING match notification to display. */
  notification: MatchNotification;
  /** True while an accept/reject action is in flight (disables the buttons). */
  busy?: boolean;
  /** Invoked when the buyer selects "Claim Deal" (accept). */
  onClaim: () => void;
  /** Invoked when the buyer selects "Keep Original Delivery" (reject). */
  onKeepOriginal: () => void;
}

/** Coerce a number|string field to a finite number, defaulting to 0. */
function toNumber(value: number | string | null | undefined): number {
  const n = typeof value === "string" ? Number(value) : value ?? 0;
  return Number.isFinite(n) ? (n as number) : 0;
}

export function MatchNotificationPopup({
  notification,
  busy = false,
  onClaim,
  onKeepOriginal,
}: MatchNotificationPopupProps) {
  const { headline, product, delivery_time_saved_hours } = notification;
  const moneySaved = toNumber(notification.money_saved);
  const distanceKm = toNumber(notification.distance_km);

  // Carbon is only shown when the backend includes it (>= 0.1 kg, Req 7.3).
  const carbon =
    notification.carbon_avoided_kg === null ||
    notification.carbon_avoided_kg === undefined
      ? null
      : toNumber(notification.carbon_avoided_kg);

  const hours = delivery_time_saved_hours;

  return (
    <div
      role="dialog"
      aria-modal="false"
      aria-live="polite"
      aria-label="Local open-box deal"
      className="fixed bottom-4 right-4 z-50 w-[min(92vw,24rem)]"
    >
      <div className="overflow-hidden rounded-amazon border border-gray-300 bg-white shadow-xl">
        {/* Deal banner — amazonOrange accent (Req 17 tokens). */}
        <div className="flex items-center gap-2 bg-amazonOrange px-4 py-2 text-amazonInk">
          <Sparkles className="h-5 w-5 shrink-0" aria-hidden="true" />
          <h2 className="text-sm font-bold leading-tight">
            {headline || LOCAL_DEAL_HEADLINE}
          </h2>
        </div>

        <div className="space-y-3 p-4">
          <p className="text-sm text-amazonInk">{LOCAL_DEAL_SUBHEADLINE}</p>

          {/* Matched product. */}
          <div className="flex items-center gap-3">
            <ProductImage
              src={productImageSrc(product)}
              alt={product.name}
              className="h-16 w-16 shrink-0 border border-gray-200"
            />
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-amazonInk">
                {product.name}
              </p>
              <p className="mt-0.5 flex items-center gap-1 text-xs text-gray-600">
                <MapPin className="h-3.5 w-3.5" aria-hidden="true" />
                {distanceKm.toFixed(2)} km away
              </p>
            </div>
          </div>

          {/* Savings summary. */}
          <dl className="space-y-1.5 rounded-amazon bg-amazonBg p-3 text-sm">
            <div className="flex items-center justify-between">
              <dt className="text-gray-700">You save</dt>
              <dd className="font-bold text-green-800">
                {inr.format(moneySaved)}
              </dd>
            </div>
            <div className="flex items-center justify-between">
              <dt className="text-gray-700">Claim bonus</dt>
              <dd className="font-bold text-green-800">
                -{inr.format(CLAIMED_DEAL_DISCOUNT)}
              </dd>
            </div>
            <div className="flex items-center justify-between">
              <dt className="flex items-center gap-1 text-gray-700">
                <Clock className="h-4 w-4" aria-hidden="true" />
                Delivery
              </dt>
              <dd className="font-medium text-amazonInk">
                {hours > 0
                  ? `Get delivery ~${hours} hours sooner`
                  : "Faster local delivery"}
              </dd>
            </div>
            {carbon !== null ? (
              <div className="flex items-center justify-between">
                <dt className="flex items-center gap-1 text-gray-700">
                  <Leaf className="h-4 w-4 text-green-700" aria-hidden="true" />
                  CO₂ avoided
                </dt>
                <dd className="font-medium text-green-800">
                  {carbon.toFixed(1)} kg
                </dd>
              </div>
            ) : null}
          </dl>

          {/* Actions — both always enabled and visible (Req 7.4, 8.2). */}
          <div className="space-y-2">
            <PrimaryButton disabled={busy} onClick={onClaim}>
              {busy ? "Claiming…" : "Claim Deal"}
            </PrimaryButton>
            <button
              type="button"
              disabled={busy}
              onClick={onKeepOriginal}
              className="inline-flex w-full items-center justify-center gap-1 rounded-amazon border border-gray-400 bg-white px-4 py-2 text-sm font-medium text-amazonInk shadow-sm hover:bg-amazonBg focus:outline-none focus-visible:ring-2 focus-visible:ring-amazonOrange disabled:cursor-not-allowed disabled:opacity-60"
            >
              <X className="h-4 w-4" aria-hidden="true" />
              Keep Original Delivery
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
