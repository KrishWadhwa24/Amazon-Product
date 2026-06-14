"use client";

/**
 * Amazon AI Item Verification Scan modal (Requirement 3.6).
 *
 * When a seller initiates a return, the frontend displays this Amazon-styled
 * scanning modal for ~2 seconds (2000ms, tolerance ±200ms) before the
 * ReturnOrder is created. The modal runs an animated scanning indicator and,
 * after the configured `durationMs`, invokes `onComplete` exactly once. The
 * caller is responsible for submitting `POST /api/returns/initiate` only after
 * `onComplete` fires — the scan must finish (be "dismissed") before the request.
 *
 * The scan is a *mocked* AI verification step: it is purely a timed visual
 * affordance and performs no real analysis. `durationMs` is a prop (defaulting
 * to 2000) so the timing is deterministically testable (task 16.3).
 */

import { useEffect, useRef, useState } from "react";
import { Loader2, ScanLine } from "lucide-react";

/** The default scan duration in milliseconds (Requirement 3.6: 2s ±200ms). */
export const DEFAULT_SCAN_DURATION_MS = 2000;

export interface AIVerificationScanModalProps {
  /** Whether the scan modal is visible and actively scanning. */
  open: boolean;
  /** Product name shown in the scan body (optional). */
  productName?: string;
  /** Image URL of the item being verified (optional). */
  imageUrl?: string;
  /**
   * How long the scan runs before `onComplete` fires, in milliseconds.
   * Defaults to {@link DEFAULT_SCAN_DURATION_MS} (2000ms). Exposed as a prop so
   * the timing can be driven deterministically under fake timers in tests.
   */
  durationMs?: number;
  /**
   * Invoked exactly once when the scan completes (after `durationMs`). The
   * caller submits the return initiation request from this callback.
   */
  onComplete: () => void;
}

/**
 * Modal that displays the "Amazon AI Item Verification Scan" while a mock scan
 * runs, then calls `onComplete`.
 */
export function AIVerificationScanModal({
  open,
  productName,
  imageUrl,
  durationMs = DEFAULT_SCAN_DURATION_MS,
  onComplete,
}: AIVerificationScanModalProps) {
  // Drive the progress bar from 0 -> 100 across the scan duration.
  const [progress, setProgress] = useState(0);

  // Keep the latest onComplete without re-arming the timer when it changes.
  const onCompleteRef = useRef(onComplete);
  useEffect(() => {
    onCompleteRef.current = onComplete;
  }, [onComplete]);

  useEffect(() => {
    if (!open) {
      setProgress(0);
      return;
    }

    // Arm a single completion timer for the configured duration. When it
    // fires, the scan is "dismissed" and the caller submits the request.
    const completionTimer = setTimeout(() => {
      setProgress(100);
      onCompleteRef.current();
    }, durationMs);

    // Animate the progress bar toward completion. This is purely visual; the
    // completion timer above is the single source of truth for `onComplete`.
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
      aria-labelledby="ai-scan-title"
    >
      <div className="w-full max-w-sm rounded-amazon border border-gray-300 bg-white p-6 text-center shadow-xl">
        <div className="flex items-center justify-center gap-2 text-amazonInk">
          <ScanLine className="h-5 w-5 text-amazonOrange" aria-hidden="true" />
          <h2 id="ai-scan-title" className="text-lg font-bold">
            Amazon AI Item Verification Scan
          </h2>
        </div>

        {/* Item being verified with an animated scanning sweep overlay. */}
        <div className="relative mx-auto mt-4 aspect-square w-40 overflow-hidden rounded-amazon border border-gray-200 bg-amazonBg">
          {imageUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={imageUrl}
              alt={productName ? `Verifying ${productName}` : "Verifying item"}
              className="h-full w-full object-contain"
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center">
              <ScanLine
                className="h-12 w-12 text-gray-400"
                aria-hidden="true"
              />
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
            Verifying item condition
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
          aria-label="AI verification scan progress"
        >
          <div
            className="h-full rounded-full bg-amazonOrange transition-[width] duration-100 ease-linear"
            style={{ width: `${progress}%` }}
          />
        </div>

        <p className="mt-3 text-xs text-gray-600">
          Please keep this window open while we verify your item.
        </p>
      </div>
    </div>
  );
}
