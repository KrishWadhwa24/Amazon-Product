"use client";

/**
 * Amazon AI Condition Grading scan modal (Requirement 11.5).
 *
 * When a seller initiates a resale listing, the frontend displays this
 * Amazon-styled grading modal for ~2 seconds (2000ms) before the ResaleListing
 * is created. The modal runs an animated scanning indicator and, after the
 * configured `durationMs`, produces a *mock* grading result — a deterministic
 * `condition_grade`, a mock captured `condition_image_url`, and a
 * `suggested_price` — then invokes `onComplete(result)` exactly once. The
 * caller submits `POST /api/resale/list` from that callback (the scan must
 * finish before the request).
 *
 * This is the analogue of {@link AIVerificationScanModal}, but instead of a
 * pass/fail verification it yields a grading result. The grade and condition
 * image stand in for the seller's *future real camera capture*: the camera
 * seam is the `condition_image_url` (a placeholder asset today) and the grading
 * model seam is {@link gradeProduct}. Both are deterministic so the listing
 * flow is reproducible in a demo and testable.
 *
 * `durationMs` is a prop (defaulting to 2000) so the timing can be driven
 * deterministically under fake timers (task 17.4).
 */

import { useEffect, useRef, useState } from "react";
import { Camera, Loader2 } from "lucide-react";

/** The default grading scan duration in milliseconds (Requirement 11.5: 2s). */
export const DEFAULT_GRADING_SCAN_DURATION_MS = 2000;

/**
 * Mock captured "live condition" image URL. Stands in for the photo a seller's
 * camera would capture; the bundled asset lives in `public/`.
 */
export const MOCK_CONDITION_IMAGE_URL = "/placeholder-condition.svg";

/** The supported condition grades (must match the backend's accepted set). */
export type ConditionGrade = "Like New" | "Good" | "Fair";

/** Ordered grade table with the price multiplier applied to the catalog price. */
const GRADE_TABLE: ReadonlyArray<{ grade: ConditionGrade; priceFactor: number }> =
  [
    { grade: "Like New", priceFactor: 0.85 },
    { grade: "Good", priceFactor: 0.7 },
    { grade: "Fair", priceFactor: 0.55 },
  ];

/** The result produced by the mock grading scan and handed to `onComplete`. */
export interface GradingResult {
  /** The mock AI condition grade (one of the supported grades). */
  condition_grade: ConditionGrade;
  /** Mock captured live-condition image URL (the camera-capture seam). */
  condition_image_url: string;
  /**
   * Suggested resale price derived from the catalog price and the grade.
   * Always `0 < suggested_price <= productPrice` (Requirement 11.2).
   */
  suggested_price: number;
}

/**
 * Deterministically derive a grade from a product key so the same product
 * always grades the same way in the demo. This is the swappable seam for a real
 * grading model.
 */
function pickGradeIndex(seed: string): number {
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) {
    // Simple, stable string hash (djb2-ish), kept positive.
    hash = (hash * 31 + seed.charCodeAt(i)) >>> 0;
  }
  return hash % GRADE_TABLE.length;
}

/** Round to 2 decimal places (currency). */
function round2(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

/**
 * Produce a deterministic mock grading result for a product. Exported so the
 * timing test and callers can assert the shape without rendering.
 *
 * The suggested price is `priceFactor × productPrice` clamped to
 * `(0, productPrice]` and rounded to 2 dp. When the catalog price is so small
 * that the factor rounds to 0.00, the suggested price falls back to the catalog
 * price so it stays strictly positive and within bound.
 */
export function gradeProduct(
  productKey: string,
  productPrice: number,
): GradingResult {
  const { grade, priceFactor } = GRADE_TABLE[pickGradeIndex(productKey)];
  const safePrice = productPrice > 0 ? productPrice : 0;
  let suggested = round2(safePrice * priceFactor);
  if (suggested <= 0) suggested = round2(safePrice);
  if (suggested > safePrice) suggested = round2(safePrice);
  return {
    condition_grade: grade,
    condition_image_url: MOCK_CONDITION_IMAGE_URL,
    suggested_price: suggested,
  };
}

export interface MockAIGradingScanModalProps {
  /** Whether the grading modal is visible and actively scanning. */
  open: boolean;
  /** Product name shown in the scan body (optional). */
  productName?: string;
  /** Image URL of the item being graded (optional). */
  imageUrl?: string;
  /**
   * Stable key (e.g. ASIN) used to deterministically pick the mock grade.
   * Falls back to the product name, then a constant, when absent.
   */
  productKey?: string;
  /** Catalog price used to derive the suggested resale price. */
  productPrice?: number;
  /**
   * How long the scan runs before `onComplete` fires, in milliseconds.
   * Defaults to {@link DEFAULT_GRADING_SCAN_DURATION_MS} (2000ms). Exposed as a
   * prop so the timing can be driven deterministically under fake timers.
   */
  durationMs?: number;
  /**
   * Invoked exactly once when the scan completes (after `durationMs`) with the
   * mock {@link GradingResult}. The caller submits the resale listing from this
   * callback.
   */
  onComplete: (result: GradingResult) => void;
}

/**
 * Modal that displays the "Amazon AI Condition Grading" scan while a mock scan
 * runs, then calls `onComplete` with a deterministic grading result.
 */
export function MockAIGradingScanModal({
  open,
  productName,
  imageUrl,
  productKey,
  productPrice = 0,
  durationMs = DEFAULT_GRADING_SCAN_DURATION_MS,
  onComplete,
}: MockAIGradingScanModalProps) {
  // Drive the progress bar from 0 -> 100 across the scan duration.
  const [progress, setProgress] = useState(0);

  // Keep the latest onComplete / inputs without re-arming the timer.
  const onCompleteRef = useRef(onComplete);
  useEffect(() => {
    onCompleteRef.current = onComplete;
  }, [onComplete]);

  const resultInputsRef = useRef({ productKey, productName, productPrice });
  useEffect(() => {
    resultInputsRef.current = { productKey, productName, productPrice };
  }, [productKey, productName, productPrice]);

  useEffect(() => {
    if (!open) {
      setProgress(0);
      return;
    }

    // Arm a single completion timer for the configured duration. When it fires,
    // the mock grading result is produced and the caller submits the listing.
    const completionTimer = setTimeout(() => {
      setProgress(100);
      const inputs = resultInputsRef.current;
      const seed = inputs.productKey || inputs.productName || "resale-item";
      onCompleteRef.current(gradeProduct(seed, inputs.productPrice ?? 0));
    }, durationMs);

    // Animate the progress bar toward completion. Purely visual; the completion
    // timer above is the single source of truth for `onComplete`.
    setProgress(0);
    const start =
      typeof performance !== "undefined" ? performance.now() : Date.now();
    const tick = setInterval(() => {
      const elapsed =
        (typeof performance !== "undefined" ? performance.now() : Date.now()) -
        start;
      const pct = Math.min(99, Math.round((elapsed / durationMs) * 100));
      setProgress(pct);
    }, 60);

    return () => {
      clearTimeout(completionTimer);
      clearInterval(tick);
    };
  }, [open, durationMs]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-amazonInk/60 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="ai-grading-title"
    >
      <div className="w-full max-w-sm rounded-amazon border border-gray-300 bg-white p-6 text-center shadow-xl">
        <div className="flex items-center justify-center gap-2 text-amazonInk">
          <Camera className="h-5 w-5 text-amazonOrange" aria-hidden="true" />
          <h2 id="ai-grading-title" className="text-lg font-bold">
            Amazon AI Condition Grading
          </h2>
        </div>

        {/* Item being graded with an animated scanning sweep overlay. */}
        <div className="relative mx-auto mt-4 aspect-square w-40 overflow-hidden rounded-amazon border border-gray-200 bg-amazonBg">
          {imageUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={imageUrl}
              alt={productName ? `Grading ${productName}` : "Grading item"}
              className="h-full w-full object-contain"
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center">
              <Camera className="h-12 w-12 text-gray-400" aria-hidden="true" />
            </div>
          )}
          {/* Sweeping scan line. */}
          <div
            className="pointer-events-none absolute inset-x-0 top-0 h-0.5 bg-amazonOrange shadow-[0_0_8px_2px_rgba(255,153,0,0.6)] motion-safe:animate-ai-scan-sweep"
            aria-hidden="true"
          />
        </div>

        <p className="mt-4 flex items-center justify-center gap-2 text-sm text-amazonInk">
          <Loader2
            className="h-4 w-4 motion-safe:animate-spin text-amazonOrange"
            aria-hidden="true"
          />
          <span>
            Grading condition
            {productName ? (
              <>
                {" "}
                for <span className="font-medium">{productName}</span>
              </>
            ) : null}
            …
          </span>
        </p>

        {/* Progress bar. */}
        <div
          className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-gray-200"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress}
          aria-label="AI condition grading progress"
        >
          <div
            className="h-full rounded-full bg-amazonOrange transition-[width] duration-100 ease-linear"
            style={{ width: `${progress}%` }}
          />
        </div>

        <p className="mt-3 text-xs text-gray-600">
          Capturing a live photo and grading your item&apos;s condition.
        </p>
      </div>
    </div>
  );
}
