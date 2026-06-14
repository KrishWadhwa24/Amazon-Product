import { describe, it } from "vitest";
import fc from "fast-check";

import { formatCountdown } from "@/components/admin/LiveCountdownTimer";

// Feature: amazon-edge-return, Property 28: Countdown formatting
//
// For any remaining-time value, formatCountdown returns zero-padded HH:MM:SS
// equal to the hours/minutes/seconds decomposition of the (floored) remaining
// seconds when positive, and exactly "00:00:00" when the remaining time is at
// or below zero (or non-finite). The component floors the remaining seconds
// before decomposing, so the expected value is derived from Math.floor(n).
//
// Values are generated spanning negatives, zero, and large positives, using
// both integer seconds (fc.integer) and fractional seconds (fc.double).
//
// Validates: Requirements 15.1, 15.4
describe("Property 28: Countdown formatting", () => {
  it("renders zero-padded HH:MM:SS for positive seconds and 00:00:00 at or below zero", () => {
    fc.assert(
      fc.property(
        fc.oneof(
          // Integer seconds spanning negatives, zero, and large positives
          // (well beyond 24h so hours are uncapped, e.g. 48:00:00).
          fc.integer({ min: -100_000, max: 500_000 }),
          // Fractional seconds across the same range to exercise flooring.
          fc.double({
            min: -100_000,
            max: 500_000,
            noNaN: true,
            noDefaultInfinity: true,
          }),
        ),
        (n) => {
          const result = formatCountdown(n);

          if (!(Number.isFinite(n) && n > 0)) {
            return result === "00:00:00";
          }

          const total = Math.floor(n);
          const expected = `${String(Math.floor(total / 3600)).padStart(
            2,
            "0",
          )}:${String(Math.floor((total % 3600) / 60)).padStart(
            2,
            "0",
          )}:${String(Math.floor(total % 60)).padStart(2, "0")}`;

          return result === expected;
        },
      ),
      { numRuns: 20 },
    );
  });
});
