"use client";

/**
 * NGO Dispatch panel for the admin operations console (Feature 2).
 *
 * Allows the operator to dispatch a single NGO_ROUTING return to the NGO
 * charity partner by entering the return order ID and clicking
 * "Dispatch to NGO". On success:
 *   - The return is marked as dispatched (removed from the NGO_QUEUED view).
 *   - The product's price is deducted from the inventory ledger and added to
 *     the "Tax Credits Accrued" metric on the dashboard.
 *   - The full recalculated metrics bundle is returned so the KPI cards
 *     refresh in one round-trip.
 *
 * Styled for the slate-950 admin shell — dark surfaces, violet accent (matching
 * the NGO_ROUTING status badge colour), aria-live region for confirmations.
 */
import { useCallback, useState } from "react";
import { Heart } from "lucide-react";

import { ApiError, api } from "@/lib/api";
import type { AdminMetrics } from "@/components/admin/KPIGrid";

// ------------------------------------------------------------------ types -- //

export interface NgoDispatchApiResponse {
  return_order_id: number;
  deducted_value: number;
  metrics: AdminMetrics;
}

export interface NgoDispatchButtonProps {
  /** Disable the action while the page is in a loading state. */
  disabled?: boolean;
  /**
   * Called after a successful dispatch so the page can refresh metrics and
   * the returns table.
   */
  onDispatched?: (result: NgoDispatchApiResponse) => void;
}

type NgoState =
  | { kind: "idle" }
  | { kind: "pending" }
  | { kind: "success"; returnOrderId: number; deductedValue: number }
  | { kind: "error"; message: string };

// --------------------------------------------------------------- component -- //

const currency = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function NgoDispatchButton({
  disabled = false,
  onDispatched,
}: NgoDispatchButtonProps) {
  const [returnIdInput, setReturnIdInput] = useState("");
  const [state, setState] = useState<NgoState>({ kind: "idle" });

  const handleDispatch = useCallback(async () => {
    const id = parseInt(returnIdInput.trim(), 10);
    if (!Number.isFinite(id) || id <= 0) {
      setState({ kind: "error", message: "Please enter a valid return order ID." });
      return;
    }

    setState({ kind: "pending" });
    try {
      const result = await api.post<NgoDispatchApiResponse>(
        "/api/admin/ngo/dispatch",
        { return_order_id: id },
      );
      setState({
        kind: "success",
        returnOrderId: result.return_order_id,
        deductedValue: Number(result.deducted_value),
      });
      setReturnIdInput("");
      onDispatched?.(result);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : "Couldn't dispatch to NGO. Please try again.";
      setState({ kind: "error", message });
    }
  }, [returnIdInput, onDispatched]);

  const pending = state.kind === "pending";

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-slate-700 bg-slate-900 p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
        Dispatch Eligible Item to NGO
      </p>
      <div className="flex gap-2">
        <input
          type="number"
          min={1}
          value={returnIdInput}
          onChange={(e) => {
            setReturnIdInput(e.target.value);
            if (state.kind !== "idle") setState({ kind: "idle" });
          }}
          placeholder="NGO Return Order ID"
          disabled={disabled || pending}
          aria-label="NGO_ROUTING return order ID to dispatch"
          className="w-44 rounded-md border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 placeholder-slate-500 focus:border-violet-400 focus:outline-none focus:ring-1 focus:ring-violet-400 disabled:cursor-not-allowed disabled:opacity-60"
        />
        <button
          type="button"
          onClick={handleDispatch}
          disabled={disabled || pending || returnIdInput.trim() === ""}
          className={[
            "inline-flex items-center justify-center gap-2",
            "rounded-md bg-violet-600 px-3 py-1.5",
            "text-sm font-semibold text-white",
            "shadow-sm transition-[filter] hover:brightness-110",
            "focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-400 focus-visible:ring-offset-2 focus-visible:ring-offset-adminSlate",
            "disabled:cursor-not-allowed disabled:opacity-60",
          ].join(" ")}
        >
          <Heart className="h-4 w-4" aria-hidden="true" />
          {pending ? "Dispatching…" : "Dispatch to NGO"}
        </button>
      </div>

      {/* Aria-live status feedback */}
      <div aria-live="polite" className="min-h-[1.25rem] text-xs">
        {state.kind === "success" ? (
          <p className="text-emerald-400">
            Return #{state.returnOrderId} dispatched to NGO —{" "}
            {currency.format(state.deductedValue)} added to Tax Credits.
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

export default NgoDispatchButton;
