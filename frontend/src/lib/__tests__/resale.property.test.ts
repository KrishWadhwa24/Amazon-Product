import { describe, it } from "vitest";
import fc from "fast-check";

import {
  RESALE_ELIGIBILITY_THRESHOLD_MS,
  isResellEligible,
} from "@/lib/resale";

// Feature: amazon-edge-return, Property 22: Resale eligibility by purchase age
//
// For any `now` and any offset, isResellEligible is true IFF the purchase
// timestamp is more than 7 days before `now`. Offsets are generated spanning
// below, exactly at, and above the 7-day boundary.
//
// Validates: Requirements 11.1
describe("Property 22: Resale eligibility by purchase age", () => {
  it("is resell-eligible iff purchased more than 7 days before now", () => {
    fc.assert(
      fc.property(
        // Reference "now" within a plausible epoch range (kept well away from
        // the bounds so subtracting the offset never underflows below 0).
        fc.integer({ min: 1_000_000_000_000, max: 4_000_000_000_000 }),
        // Offset in seconds around the 7-day boundary (7 * 24 * 3600 = 604800),
        // spanning clearly below, exactly at, and clearly above the threshold.
        fc.integer({ min: 0, max: 14 * 24 * 3600 }),
        (nowMs, offsetSeconds) => {
          const now = new Date(nowMs);
          const offsetMs = offsetSeconds * 1000;
          const purchasedAt = new Date(nowMs - offsetMs);
          const purchasedAtISO = purchasedAt.toISOString();

          const expected = offsetMs > RESALE_ELIGIBILITY_THRESHOLD_MS;

          return isResellEligible(purchasedAtISO, now) === expected;
        },
      ),
      { numRuns: 20 },
    );
  });
});
