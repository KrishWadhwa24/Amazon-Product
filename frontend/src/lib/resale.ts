/**
 * Resale eligibility helpers.
 *
 * The orders UI shows the "Resell via Amazon" action only for purchases that
 * are past the return window. The eligibility rule (Requirement 11.1) is that
 * an order's `purchased_at` must be *more than* 7 days before the current time.
 *
 * On the backend this is computed server-side and surfaced to the frontend as a
 * `resell_eligible` boolean. This pure helper mirrors that rule so the orders UI
 * can compute or verify eligibility locally, and so the rule can be exercised by
 * property-based tests.
 */

/** Number of milliseconds in the 7-day resale eligibility threshold. */
export const RESALE_ELIGIBILITY_THRESHOLD_MS = 7 * 24 * 60 * 60 * 1000;

/**
 * Returns true iff the purchase occurred strictly more than 7 days before
 * `now`. A purchase exactly 7 days old (or newer) is not yet resale-eligible.
 *
 * @param purchasedAtISO ISO-8601 timestamp of when the order was purchased.
 * @param now The reference "current time".
 */
export function isResellEligible(purchasedAtISO: string, now: Date): boolean {
  const purchasedAtMs = Date.parse(purchasedAtISO);
  if (Number.isNaN(purchasedAtMs)) {
    return false;
  }
  return now.getTime() - purchasedAtMs > RESALE_ELIGIBILITY_THRESHOLD_MS;
}
