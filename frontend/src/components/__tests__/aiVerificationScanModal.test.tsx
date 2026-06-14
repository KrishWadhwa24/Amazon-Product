import { describe, expect, it, vi, afterEach } from "vitest";
import { act, render, screen } from "@testing-library/react";
import {
  AIVerificationScanModal,
  DEFAULT_SCAN_DURATION_MS,
} from "../AIVerificationScanModal";

/**
 * Unit tests for the AI verification scan modal timing + submit contract (Req 3.6).
 *
 * Requirement 3.6 states the Frontend displays the "Amazon AI Item Verification
 * Scan" modal for 2 seconds (±200ms) and submits the return initiation request
 * ONLY after the modal is dismissed. The modal models that "dismissal" as the
 * `onComplete` callback firing after `durationMs`. `onComplete` is therefore the
 * submission trigger: these tests assert it never fires early, fires exactly once
 * at the duration boundary, and never fires when the modal is closed.
 *
 * Timing is exercised deterministically with Vitest fake timers so we can assert
 * the precise boundary (e.g. 2000ms) rather than relying on wall-clock delays.
 */

afterEach(() => {
  // Always restore real timers so fake timers never leak between tests.
  vi.useRealTimers();
});

describe("AIVerificationScanModal — timing and submit contract (Req 3.6)", () => {
  it("shows the verification heading while open and defers onComplete until the duration elapses", () => {
    vi.useFakeTimers();
    const onComplete = vi.fn();

    render(
      <AIVerificationScanModal
        open
        productName="Sony WH-CH520 Wireless Headphones"
        onComplete={onComplete}
      />,
    );

    // The Amazon-styled scan modal is visible immediately.
    expect(
      screen.getByRole("heading", { name: "Amazon AI Item Verification Scan" }),
    ).toBeInTheDocument();

    // Submission trigger must NOT fire before the full duration elapses.
    act(() => {
      vi.advanceTimersByTime(DEFAULT_SCAN_DURATION_MS - 1);
    });
    expect(onComplete).not.toHaveBeenCalled();

    // Crossing the duration boundary completes the scan exactly once.
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("honors a custom durationMs and fires onComplete exactly once at that boundary", () => {
    vi.useFakeTimers();
    const onComplete = vi.fn();
    const durationMs = 2000;

    render(
      <AIVerificationScanModal
        open
        durationMs={durationMs}
        onComplete={onComplete}
      />,
    );

    // Just before the boundary: still scanning, no submission yet.
    act(() => {
      vi.advanceTimersByTime(durationMs - 1);
    });
    expect(onComplete).not.toHaveBeenCalled();

    // At the boundary: completes exactly once.
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("renders nothing and never calls onComplete when closed", () => {
    vi.useFakeTimers();
    const onComplete = vi.fn();

    const { container } = render(
      <AIVerificationScanModal open={false} onComplete={onComplete} />,
    );

    // Closed modal renders no DOM and shows no heading.
    expect(container.firstChild).toBeNull();
    expect(
      screen.queryByRole("heading", {
        name: "Amazon AI Item Verification Scan",
      }),
    ).not.toBeInTheDocument();

    // Even after well past the scan duration, the submission trigger never fires.
    act(() => {
      vi.advanceTimersByTime(DEFAULT_SCAN_DURATION_MS * 5);
    });
    expect(onComplete).not.toHaveBeenCalled();
  });

  it("calls onComplete only once even if timers advance well beyond the duration", () => {
    vi.useFakeTimers();
    const onComplete = vi.fn();

    render(<AIVerificationScanModal open onComplete={onComplete} />);

    // Advance far past completion; the single completion timer must not re-fire.
    act(() => {
      vi.advanceTimersByTime(DEFAULT_SCAN_DURATION_MS);
    });
    expect(onComplete).toHaveBeenCalledTimes(1);

    act(() => {
      vi.advanceTimersByTime(DEFAULT_SCAN_DURATION_MS * 10);
    });
    expect(onComplete).toHaveBeenCalledTimes(1);
  });
});
