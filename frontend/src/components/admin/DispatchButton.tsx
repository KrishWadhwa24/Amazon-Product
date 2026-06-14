"use client";

/**
 * Batch Dispatch button for the admin operations console (Requirements 16.1–16.5).
 *
 * Renders an operator action that batch-dispatches every RTO_QUEUED return to a
 * fulfillment hub by POSTing `POST /api/admin/dispatch` with the supported
 * action `BATCH_FC_RTO` and a (demo-constant) hub identifier. On success it
 * surfaces a confirmation showing the number of returns transitioned
 * (Requirement 16.1) — including the zero case (Requirement 16.5) — and invokes
 * {@link DispatchButtonProps.onDispatched} so the page can refetch metrics and
 * the returns table (the response also carries recalculated metrics per
 * Requirement 16.2). Backend rejections (`UNSUPPORTED_ACTION` /
 * `HUB_REQUIRED`) are surfaced inline as an error message (Requirements 16.3,
 * 16.4).
 *
 * Designed for the slate-950 admin shell: dark surfaces, an amber primary
 * accent, and an aria-live status region so the confirmation/error is
 * announced.
 */
import { useCallback, useState } from "react";
import { Truck } from "lucide-react";

import { ApiError, api } from "@/lib/api";
import type { AdminMetrics } from "@/components/admin/KPIGrid";

/** The supported dispatch action (mirrors the backend's `BATCH_FC_RTO`). */
export const DISPATCH_ACTION = "BATCH_FC_RTO" as const;

/** Default demo hub identifier dispatched to (Requirement 16.4 non-empty hub). */
export const DEFAULT_HUB_ID = "IND-BLR-01" as const;

/** Shape of the `POST /api/admin/dispatch` success payload (task 24.6). */
export interface DispatchResponse {
  /** Number of RTO_QUEUED returns moved to FC_TRANSIT (>= 0). */
  transitioned_count: number;
  /** Recalculated post-dispatch KPI bundle (Requirement 16.2). */
  metrics: AdminMetrics;
}

export interface DispatchButtonProps {
  /**
   * Hub identifier to dispatch to. Defaults to {@link DEFAULT_HUB_ID} for the
   * demo; a non-empty value is required by the backend (Requirement 16.4).
   */
  hubId?: string;
  /** Disable the action (e.g. while the table is loading). */
  disabled?: boolean;
  /**
   * Called after a successful dispatch so the page can refetch metrics + the
   * returns table. Receives the recalculated metrics from the response.
   */
  onDispatched?: (result: DispatchResponse) => void;
}

type DispatchState =
  | { kind: "idle" }
  | { kind: "pending" }
  | { kind: "success"; count: number }
  | { kind: "error"; message: string };

export function DispatchButton({
  hubId = DEFAULT_HUB_ID,
  disabled = false,
  onDispatched,
}: DispatchButtonProps) {
  const [state, setState] = useState<DispatchState>({ kind: "idle" });

  const handleDispatch = useCallback(async () => {
    setState({ kind: "pending" });
    try {
      const result = await api.post<DispatchResponse>("/api/admin/dispatch", {
        action: DISPATCH_ACTION,
        hub_id: hubId,
      });
      setState({ kind: "success", count: result.transitioned_count });
      onDispatched?.(result);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : "We couldn't dispatch queued returns right now. Please try again.";
      setState({ kind: "error", message });
    }
  }, [hubId, onDispatched]);

  const pending = state.kind === "pending";

  return (
    <div className="flex flex-col items-end gap-2">
      <button
        type="button"
        onClick={handleDispatch}
        disabled={disabled || pending}
        className={[
          "inline-flex items-center justify-center gap-2",
          "rounded-md bg-amazonOrange px-4 py-2",
          "text-sm font-semibold text-slate-950",
          "shadow-sm transition-[filter] hover:brightness-95",
          "focus:outline-none focus-visible:ring-2 focus-visible:ring-amazonOrange focus-visible:ring-offset-2 focus-visible:ring-offset-adminSlate",
          "disabled:cursor-not-allowed disabled:opacity-60",
        ].join(" ")}
      >
        <Truck className="h-4 w-4" aria-hidden="true" />
        {pending ? "Dispatching…" : "Batch Dispatch to FC"}
      </button>

      {/* Confirmation / error status, announced to assistive tech. */}
      <div aria-live="polite" className="min-h-[1.25rem] text-right text-xs">
        {state.kind === "success" ? (
          <p className="text-emerald-400">
            {state.count === 0
              ? "No queued returns to dispatch."
              : `Dispatched ${state.count} return${
                  state.count === 1 ? "" : "s"
                } to ${hubId}.`}
          </p>
        ) : state.kind === "error" ? (
          <p role="alert" className="text-red-400">
            {state.message}
          </p>
        ) : null}
      </div>
    </div>
  );
}

export default DispatchButton;
