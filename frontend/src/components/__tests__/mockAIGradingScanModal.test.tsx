import { describe, expect, it, vi, afterEach } from "vitest";
import { act, render, screen } from "@testing-library/react";
import {
  MockAIGradingScanModal,
  DEFAULT_GRADING_SCAN_DURATION_MS,
  gradeProduct,
  type ConditionGrade,
} from "../MockAIGradingScanModal";

/**
 * Unit tests for the mock AI grading scan modal timing + result contract (Req 11.5).
 *
 * Requirement 11.5 states the Frontend displays a mock AI scan for 2 seconds
 * before the ResaleListing is created. The modal models that "creation trigger"
 * as the `onComplete(result)` callback firing after `durationMs`. `onComplete`
 * is therefore the listing-submission trigger: these tests assert it never fires
 * early, fires exactly once at the duration boundary with a valid GradingResult,
 * never fires when the modal is closed, and never re-fires afterward.
 *
 * A valid GradingResult has a condition_grade in {"Like New", "Good", "Fair"},
 * a non-empty condition_image_url, and 0 < suggested_price <= productPrice
 * (Req 11.2's price bound, surfaced by the mock grader).
 *
 * Timing is exercised deterministically with Vitest fake timers so we can assert
 * the precise 2000ms boundary rather than relying on wall-clock delays.
 *
 * Validates: Requirements 11.5
 */

const VALID_GRADES: readonly ConditionGrade[] = ["Like New", "Good", "Fair"];
const PRODUCT_PRICE = 4990;

afterEach(() => {
  // Always restore real timers so fake timers never leak between tests.
  vi.useRealTimers();
});

describe("MockAIGradingScanModal — timing and grading-result contract (Req 11.5)", () => {
  it("shows the grading heading while open and defers onComplete with a valid result until the duration elapses", () => {
    vi.useFakeTimers();
    const onComplete = vi.fn();

    render(
      <MockAIGradingScanModal
        open
        productName="Sony WH-CH520 Wireless Headphones"
        productKey="B0BS1PRYB4"
        productPrice={PRODUCT_PRICE}
        onComplete={onComplete}
      />,
    );

    // The Amazon-styled grading modal is visible immediately.
    expect(
      screen.getByRole("heading", { name: "Amazon AI Condition Grading" }),
    ).toBeInTheDocument();

    // Listing-creation trigger must NOT fire before the full duration elapses.
    act(() => {
      vi.advanceTimersByTime(DEFAULT_GRADING_SCAN_DURATION_MS - 1);
    });
    expect(onComplete).not.toHaveBeenCalled();

    // Crossing the 2000ms boundary completes the scan exactly once.
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(onComplete).toHaveBeenCalledTimes(1);

    // The single result handed to the caller is a valid grading result.
    const result = onComplete.mock.calls[0][0];
    expect(VALID_GRADES).toContain(result.condition_grade);
    expect(typeof result.condition_image_url).toBe("string");
    expect(result.condition_image_url.length).toBeGreaterThan(0);
    expect(result.suggested_price).toBeGreaterThan(0);
    expect(result.suggested_price).toBeLessThanOrEqual(PRODUCT_PRICE);
  });

  it("renders nothing and never calls onComplete when closed", () => {
    vi.useFakeTimers();
    const onComplete = vi.fn();

    const { container } = render(
      <MockAIGradingScanModal
        open={false}
        productPrice={PRODUCT_PRICE}
        onComplete={onComplete}
      />,
    );

    // Closed modal renders no DOM and shows no heading.
    expect(container.firstChild).toBeNull();
    expect(
      screen.queryByRole("heading", { name: "Amazon AI Condition Grading" }),
    ).not.toBeInTheDocument();

    // Even well past the scan duration, the creation trigger never fires.
    act(() => {
      vi.advanceTimersByTime(DEFAULT_GRADING_SCAN_DURATION_MS * 5);
    });
    expect(onComplete).not.toHaveBeenCalled();
  });

  it("calls onComplete only once even if timers advance well beyond the duration", () => {
    vi.useFakeTimers();
    const onComplete = vi.fn();

    render(
      <MockAIGradingScanModal
        open
        productKey="B0BS1PRYB4"
        productPrice={PRODUCT_PRICE}
        onComplete={onComplete}
      />,
    );

    // Advance to completion; the single completion timer fires once.
    act(() => {
      vi.advanceTimersByTime(DEFAULT_GRADING_SCAN_DURATION_MS);
    });
    expect(onComplete).toHaveBeenCalledTimes(1);

    // Advance far past completion; it must not re-fire.
    act(() => {
      vi.advanceTimersByTime(DEFAULT_GRADING_SCAN_DURATION_MS * 10);
    });
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("gradeProduct is deterministic and stays within the price bound", () => {
    // Same inputs always yield the same grade (deterministic seam).
    const first = gradeProduct("B0BS1PRYB4", PRODUCT_PRICE);
    const second = gradeProduct("B0BS1PRYB4", PRODUCT_PRICE);
    expect(second).toEqual(first);

    // Shape + bounds hold for the produced result.
    expect(VALID_GRADES).toContain(first.condition_grade);
    expect(first.condition_image_url.length).toBeGreaterThan(0);
    expect(first.suggested_price).toBeGreaterThan(0);
    expect(first.suggested_price).toBeLessThanOrEqual(PRODUCT_PRICE);
  });
});
