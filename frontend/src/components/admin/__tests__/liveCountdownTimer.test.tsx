import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import {
  DANGER_WINDOW_SECONDS,
  LiveCountdownTimer,
  formatCountdown,
  isDanger,
} from "@/components/admin/LiveCountdownTimer";

/**
 * Unit tests for the admin LiveCountdownTimer styling (Requirements 15.2, 15.3).
 *
 * The timer renders a span with `data-danger="true|false"`:
 *   - remaining in (0, 7200) s  → red, blinking, data-danger="true" (Req 15.2)
 *   - remaining >= 7200 s        → default color, data-danger="false" (Req 15.3)
 *   - remaining <= 0             → frozen "00:00:00" (Req 15.4)
 *
 * Time is driven deterministically via the injected `nowFn` clock seam so the
 * assertions do not depend on the wall clock or on advancing timers.
 */

// Fixed "now" used as the clock seam in every scenario below.
const NOW_MS = Date.parse("2024-06-01T00:00:00.000Z");
const nowFn = () => NOW_MS;

/** Build an ISO expiry `offsetSeconds` away from the fixed NOW. */
function expiryAt(offsetSeconds: number): string {
  return new Date(NOW_MS + offsetSeconds * 1000).toISOString();
}

function timerSpan(container: HTMLElement): HTMLElement {
  const span = container.querySelector("[data-danger]");
  if (!span) throw new Error("LiveCountdownTimer span not found");
  return span as HTMLElement;
}

describe("isDanger — danger window boundaries (Req 15.2, 15.3)", () => {
  it("is true strictly inside (0, 7200)", () => {
    expect(isDanger(3600)).toBe(true);
    expect(isDanger(1)).toBe(true);
    expect(isDanger(DANGER_WINDOW_SECONDS - 1)).toBe(true);
  });

  it("is false at and beyond the 2-hour boundary", () => {
    expect(isDanger(DANGER_WINDOW_SECONDS)).toBe(false); // 7200
    expect(isDanger(7201)).toBe(false);
  });

  it("is false at or below zero", () => {
    expect(isDanger(0)).toBe(false);
    expect(isDanger(-10)).toBe(false);
  });
});

describe("formatCountdown", () => {
  it("zero-pads HH:MM:SS and clamps non-positive values to 00:00:00", () => {
    expect(formatCountdown(3600)).toBe("01:00:00");
    expect(formatCountdown(3 * 3600)).toBe("03:00:00");
    expect(formatCountdown(0)).toBe("00:00:00");
    expect(formatCountdown(-5)).toBe("00:00:00");
  });
});

describe("LiveCountdownTimer — styling (Req 15.2, 15.3)", () => {
  it("renders red + danger when remaining is within 2 hours (1h out)", () => {
    const { container } = render(
      <LiveCountdownTimer expiresAt={expiryAt(3600)} nowFn={nowFn} />,
    );
    const span = timerSpan(container);

    expect(span.getAttribute("data-danger")).toBe("true");
    expect(span.className).toContain("text-red-500");
    expect(span).toHaveTextContent("01:00:00");
  });

  it("renders default color without danger when remaining is >= 2 hours (3h out)", () => {
    const { container } = render(
      <LiveCountdownTimer expiresAt={expiryAt(3 * 3600)} nowFn={nowFn} />,
    );
    const span = timerSpan(container);

    expect(span.getAttribute("data-danger")).toBe("false");
    expect(span.className).toContain("text-slate-200");
    expect(span.className).not.toContain("text-red-500");
    expect(span).toHaveTextContent("03:00:00");
  });

  it("is not in danger exactly at the 2-hour boundary (7200s out)", () => {
    const { container } = render(
      <LiveCountdownTimer
        expiresAt={expiryAt(DANGER_WINDOW_SECONDS)}
        nowFn={nowFn}
      />,
    );
    const span = timerSpan(container);
    expect(span.getAttribute("data-danger")).toBe("false");
    expect(span).toHaveTextContent("02:00:00");
  });

  it("freezes at 00:00:00 when the expiry is in the past (Req 15.4)", () => {
    const { container } = render(
      <LiveCountdownTimer expiresAt={expiryAt(-60)} nowFn={nowFn} />,
    );
    const span = timerSpan(container);

    expect(span).toHaveTextContent("00:00:00");
    expect(span.getAttribute("data-danger")).toBe("false");
    expect(span.className).not.toContain("text-red-500");
  });
});
