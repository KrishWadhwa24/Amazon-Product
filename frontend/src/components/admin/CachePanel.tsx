"use client";

/**
 * Admin Cache Management Panel.
 *
 * Two actions for the operations dashboard:
 *   1. "Add to Cache" — moves a SCANNING return into the local micro-warehouse
 *      cache by POSTing `POST /api/admin/cache/add` with a return order id.
 *      On success the cache KPI counts update immediately.
 *   2. "Dispatch to FC" — sends every cached (MICROWAREHOUSE) return to the
 *      main fulfilment centre by POSTing `POST /api/admin/cache/dispatch`.
 *      On success the cache resets to 0 and the full metrics bundle refreshes.
 *
 * Designed for the slate-950 admin shell — dark surfaces, amber accents,
 * aria-live status regions so confirmations are announced to assistive tech.
 */
import { useCallback, useState } from "react";
import { Archive, SendToBack } from "lucide-react";

import { ApiError, api } from "@/lib/api";
import type { AdminMetrics } from "@/components/admin/KPIGrid";

// ------------------------------------------------------------------ types -- //

export interface CacheAddApiResponse {
  return_order_id: number;
  cache_used: number;
  cache_total: number;
}

export interface CacheDispatchApiResponse {
  dispatched_count: number;
  metrics: AdminMetrics;
}

export interface CachePanelProps {
  /** Disable both actions while the page is in a loading state. */
  disabled?: boolean;
  /**
   * Called after a successful "Add to Cache" so the page can update the
   * cache KPI counts without a full metrics refetch.
   */
  onCacheAdded?: (result: CacheAddApiResponse) => void;
  /**
   * Called after a successful "Dispatch to FC" so the page can refresh the
   * metrics bundle and the returns table.
   */
  onCacheDispatched?: (result: CacheDispatchApiResponse) => void;
}

type AddState =
  | { kind: "idle" }
  | { kind: "pending" }
  | { kind: "success"; returnOrderId: number; cacheUsed: number; cacheTotal: number }
  | { kind: "error"; message: string };

type DispatchState =
  | { kind: "idle" }
  | { kind: "pending" }
  | { kind: "success"; count: number }
  | { kind: "error"; message: string };

// --------------------------------------------------------------- component -- //

export function CachePanel({
  disabled = false,
  onCacheAdded,
  onCacheDispatched,
}: CachePanelProps) {
  const [returnIdInput, setReturnIdInput] = useState("");
  const [addState, setAddState] = useState<AddState>({ kind: "idle" });
  const [dispatchState, setDispatchState] = useState<DispatchState>({ kind: "idle" });

  // ---- Add to Cache ---- //
  const handleAddToCache = useCallback(async () => {
    const id = parseInt(returnIdInput.trim(), 10);
    if (!Number.isFinite(id) || id <= 0) {
      setAddState({ kind: "error", message: "Please enter a valid return order ID." });
      return;
    }
    setAddState({ kind: "pending" });
    try {
      const result = await api.post<CacheAddApiResponse>("/api/admin/cache/add", {
        return_order_id: id,
      });
      setAddState({
        kind: "success",
        returnOrderId: result.return_order_id,
        cacheUsed: result.cache_used,
        cacheTotal: result.cache_total,
      });
      setReturnIdInput("");
      onCacheAdded?.(result);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : "Couldn't add to cache. Please try again.";
      setAddState({ kind: "error", message });
    }
  }, [returnIdInput, onCacheAdded]);

  // ---- Dispatch Cache to FC ---- //
  const handleDispatchToFC = useCallback(async () => {
    setDispatchState({ kind: "pending" });
    try {
      const result = await api.post<CacheDispatchApiResponse>(
        "/api/admin/cache/dispatch",
      );
      setDispatchState({ kind: "success", count: result.dispatched_count });
      onCacheDispatched?.(result);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : "Couldn't dispatch cache to FC. Please try again.";
      setDispatchState({ kind: "error", message });
    }
  }, [onCacheDispatched]);

  const addPending = addState.kind === "pending";
  const dispatchPending = dispatchState.kind === "pending";
  const anyPending = addPending || dispatchPending;

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-slate-700 bg-slate-900 p-4 sm:flex-row sm:items-start sm:gap-6">
      {/* ---- Add to Cache ---- */}
      <div className="flex flex-1 flex-col gap-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          Add Scanning Product to Cache
        </p>
        <div className="flex gap-2">
          <input
            type="number"
            min={1}
            value={returnIdInput}
            onChange={(e) => {
              setReturnIdInput(e.target.value);
              if (addState.kind !== "idle") setAddState({ kind: "idle" });
            }}
            placeholder="Return Order ID"
            disabled={disabled || anyPending}
            aria-label="Return order ID to add to cache"
            className="w-36 rounded-md border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 placeholder-slate-500 focus:border-amazonOrange focus:outline-none focus:ring-1 focus:ring-amazonOrange disabled:cursor-not-allowed disabled:opacity-60"
          />
          <button
            type="button"
            onClick={handleAddToCache}
            disabled={disabled || anyPending || returnIdInput.trim() === ""}
            className={[
              "inline-flex items-center justify-center gap-2",
              "rounded-md bg-slate-700 px-3 py-1.5",
              "text-sm font-semibold text-slate-100",
              "border border-slate-600 shadow-sm transition-[filter] hover:bg-slate-600",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-amazonOrange focus-visible:ring-offset-2 focus-visible:ring-offset-adminSlate",
              "disabled:cursor-not-allowed disabled:opacity-60",
            ].join(" ")}
          >
            <Archive className="h-4 w-4" aria-hidden="true" />
            {addPending ? "Adding…" : "Add to Cache"}
          </button>
        </div>

        {/* Status feedback */}
        <div aria-live="polite" className="min-h-[1.25rem] text-xs">
          {addState.kind === "success" ? (
            <p className="text-emerald-400">
              Return #{addState.returnOrderId} cached — {addState.cacheUsed}/
              {addState.cacheTotal} used.
            </p>
          ) : addState.kind === "error" ? (
            <p role="alert" className="text-red-400">
              {addState.message}
            </p>
          ) : null}
        </div>
      </div>

      {/* Divider */}
      <div className="hidden w-px self-stretch bg-slate-700 sm:block" aria-hidden="true" />
      <div className="h-px bg-slate-700 sm:hidden" aria-hidden="true" />

      {/* ---- Dispatch to FC ---- */}
      <div className="flex flex-col gap-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          Dispatch Cache to Main FC
        </p>
        <button
          type="button"
          onClick={handleDispatchToFC}
          disabled={disabled || anyPending}
          className={[
            "inline-flex items-center justify-center gap-2",
            "rounded-md bg-amazonOrange px-4 py-1.5",
            "text-sm font-semibold text-slate-950",
            "shadow-sm transition-[filter] hover:brightness-95",
            "focus:outline-none focus-visible:ring-2 focus-visible:ring-amazonOrange focus-visible:ring-offset-2 focus-visible:ring-offset-adminSlate",
            "disabled:cursor-not-allowed disabled:opacity-60",
          ].join(" ")}
        >
          <SendToBack className="h-4 w-4" aria-hidden="true" />
          {dispatchPending ? "Dispatching…" : "Dispatch to FC"}
        </button>

        {/* Status feedback */}
        <div aria-live="polite" className="min-h-[1.25rem] text-xs">
          {dispatchState.kind === "success" ? (
            <p className="text-emerald-400">
              {dispatchState.count === 0
                ? "Cache was already empty."
                : `${dispatchState.count} item${dispatchState.count === 1 ? "" : "s"} dispatched — cache reset to 0.`}
            </p>
          ) : dispatchState.kind === "error" ? (
            <p role="alert" className="text-red-400">
              {dispatchState.message}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export default CachePanel;
