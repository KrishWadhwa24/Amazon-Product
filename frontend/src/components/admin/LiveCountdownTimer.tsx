"use client";

/**
 * Admin live countdown timer (Requirement 15).
 *
 * Renders the remaining time until a ReturnOrder's `expires_at`, ticking once
 * per second and formatted as zero-padded `HH:MM:SS` (Req 15.1). Styling is
 * driven by the remaining seconds:
 *
 *   - remaining in `(0, 7200)` s (< 2 hours) → red text that blinks (alternates
 *     between fully visible and fully hidden) at a 1-second interval (Req 15.2).
 *   - remaining `>= 7200` s → default operations-table color, no blink
 *     (Req 15.3).
 *   - remaining `<= 0` → frozen "00:00:00", the ticking interval is cleared so
 *     the value stops decrementing (Req 15.4).
 *
 * The interval is cleaned up on unmount. The component is a client component
 * and computes the current time only after mount, so it is robust to SSR (no
 * `Date.now()` is read during a server render that could cause a hydration
 * mismatch).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

/** Seconds in the "nearing expiry" danger window (2 hours). */
export const DANGER_WINDOW_SECONDS = 7200;

/**
 * Decompose a remaining-seconds value into a zero-padded `HH:MM:SS` string.
 *
 * Values at or below zero (and non-finite values) format as exactly
 * "00:00:00" (Req 15.4). Fractional seconds are floored. Hours are not capped,
 * so a 48-hour window renders as "48:00:00".
 */
export function formatCountdown(remainingSeconds: number): string {
  const total =
    Number.isFinite(remainingSeconds) && remainingSeconds > 0
      ? Math.floor(remainingSeconds)
      : 0;
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
}

/** True when `remaining` is inside the blinking danger window `(0, 7200)` s. */
export function isDanger(remainingSeconds: number): boolean {
  return remainingSeconds > 0 && remainingSeconds < DANGER_WINDOW_SECONDS;
}

export interface LiveCountdownTimerProps {
  /** ISO-8601 timestamp at which the ReturnOrder expires. */
  expiresAt: string;
  /** Optional extra classes applied to the rendered text element. */
  className?: string;
  /**
   * Clock seam (returns epoch milliseconds). Defaults to `Date.now`; injected
   * by tests to drive deterministic remaining-time scenarios.
   */
  nowFn?: () => number;
}

/**
 * Live, self-updating countdown for the admin operations table.
 */
export function LiveCountdownTimer({
  expiresAt,
  className = "",
  nowFn,
}: LiveCountdownTimerProps) {
  // Keep the clock seam stable across renders so the tick effect does not
  // re-subscribe every render when a caller passes an inline arrow.
  const nowRef = useRef<() => number>(nowFn ?? (() => Date.now()));
  nowRef.current = nowFn ?? (() => Date.now());

  const expiryMs = useMemo(() => Date.parse(expiresAt), [expiresAt]);

  const computeRemaining = useCallback((): number => {
    if (!Number.isFinite(expiryMs)) return 0;
    return Math.floor((expiryMs - nowRef.current()) / 1000);
  }, [expiryMs]);

  // Start at 0 on the server / first paint to avoid a hydration mismatch; the
  // real remaining time is computed in the mount effect below.
  const [remaining, setRemaining] = useState(0);
  const [visible, setVisible] = useState(true);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Tick once per second from `expires_at - now`, clearing the interval once we
  // reach zero so the value freezes at "00:00:00" (Req 15.1, 15.4).
  useEffect(() => {
    const clear = () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };

    const initial = computeRemaining();
    setRemaining(initial);
    if (initial <= 0) {
      return clear;
    }

    intervalRef.current = setInterval(() => {
      const next = computeRemaining();
      if (next <= 0) {
        setRemaining(0);
        clear();
      } else {
        setRemaining(next);
      }
    }, 1000);

    return clear;
  }, [computeRemaining]);

  const danger = isDanger(remaining);

  // Blink at 1 Hz while in the danger window; otherwise stay fully visible
  // (Req 15.2, 15.3).
  useEffect(() => {
    if (!danger) {
      setVisible(true);
      return;
    }
    const id = setInterval(() => setVisible((v) => !v), 1000);
    return () => clearInterval(id);
  }, [danger]);

  const colorClass = danger ? "text-red-500" : "text-slate-200";

  return (
    <span
      className={`font-mono tabular-nums ${colorClass} ${className}`.trim()}
      style={{ visibility: danger && !visible ? "hidden" : "visible" }}
      data-danger={danger ? "true" : "false"}
      aria-label={`Time remaining ${formatCountdown(remaining)}`}
    >
      {formatCountdown(remaining)}
    </span>
  );
}

export default LiveCountdownTimer;
