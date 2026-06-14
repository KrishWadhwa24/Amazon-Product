"use client";

/**
 * Admin Operations Dashboard shell (Requirements 13.2, 13.4, 17.3).
 *
 * This is the operations console at `/admin/operations`. The global root
 * layout wraps every page in the light customer-facing NavBar + centered
 * `main`. To make this route read as a dark internal tool, the page renders a
 * full-bleed slate-950 (`adminSlate`, #020617) wrapper that visually overrides
 * the light shell: negative margins cancel the `main` padding/max-width and a
 * `min-h-screen` dark container fills the viewport (Req 17.3).
 *
 * On mount it fetches `GET /api/admin/metrics` and renders the four-column
 * {@link KPIGrid} (Req 13.2), handling loading and error states. Zero metric
 * values render explicitly rather than blank (Req 13.4).
 *
 * Below the KPIs it renders the {@link StatusFilter} + {@link OperationsDataTable}.
 * Changing the filter refetches `GET /api/admin/returns?status=...` and the
 * table shows only matching rows (Req 14.6, 14.7); the default "All" filter
 * shows every return. Each row's Time Remaining cell ticks live via the
 * {@link LiveCountdownTimer} (Req 15). The header hosts the {@link DispatchButton}
 * which batch-dispatches RTO_QUEUED returns and refreshes metrics + the table
 * (Req 16).
 */
import { useCallback, useEffect, useState } from "react";
import { LayoutDashboard } from "lucide-react";

import { KPIGrid, type AdminMetrics } from "@/components/admin/KPIGrid";
import { DispatchButton } from "@/components/admin/DispatchButton";
import {
  OperationsDataTable,
  type AdminReturnRow,
} from "@/components/admin/OperationsDataTable";
import {
  StatusFilter,
  toStatusQueryParam,
  type StatusFilterValue,
} from "@/components/admin/StatusFilter";
import { api } from "@/lib/api";

export default function AdminOperationsPage() {
  const [metrics, setMetrics] = useState<AdminMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Operations data table state (Req 14.4–14.7).
  const [statusFilter, setStatusFilter] = useState<StatusFilterValue>("All");
  const [rows, setRows] = useState<AdminReturnRow[]>([]);
  const [rowsLoading, setRowsLoading] = useState(true);
  const [rowsError, setRowsError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);

    (async () => {
      try {
        const data = await api.get<AdminMetrics>("/api/admin/metrics");
        if (active) setMetrics(data);
      } catch {
        if (active) {
          setError(
            "We couldn't load operations metrics right now. Please try again.",
          );
        }
      } finally {
        if (active) setLoading(false);
      }
    })();

    return () => {
      active = false;
    };
  }, []);

  // Refetch the returns table whenever the status filter changes (Req 14.6, 14.7).
  const loadReturns = useCallback((filter: StatusFilterValue) => {
    let active = true;
    setRowsLoading(true);
    setRowsError(null);

    (async () => {
      try {
        const status = toStatusQueryParam(filter);
        const data = await api.get<AdminReturnRow[]>(
          `/api/admin/returns?status=${encodeURIComponent(status)}`,
        );
        if (active) setRows(Array.isArray(data) ? data : []);
      } catch {
        if (active) {
          setRowsError(
            "We couldn't load active returns right now. Please try again.",
          );
          setRows([]);
        }
      } finally {
        if (active) setRowsLoading(false);
      }
    })();

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => loadReturns(statusFilter), [loadReturns, statusFilter]);

  // After a batch dispatch: apply the recalculated metrics from the response
  // (Req 16.2) and refetch the returns table so dispatched (now FC_TRANSIT)
  // returns drop out of the RTO_QUEUED view (Req 16.1).
  const handleDispatched = useCallback(
    (result: { metrics: AdminMetrics }) => {
      setMetrics(result.metrics);
      loadReturns(statusFilter);
    },
    [loadReturns, statusFilter],
  );

  return (
    // Full-bleed dark override of the light root layout (Req 17.3).
    // `-mx-4 -my-6` cancels the <main> padding; `min-h-screen` fills the area.
    <div className="-mx-4 -my-6 min-h-screen bg-adminSlate text-slate-100">
      <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <header className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
          <div className="flex items-center gap-3">
            <span className="inline-flex h-10 w-10 items-center justify-center rounded-md bg-slate-800 text-amazonOrange">
              <LayoutDashboard className="h-5 w-5" aria-hidden="true" />
            </span>
            <div>
              <h1 className="text-xl font-bold text-white">
                Operations Dashboard
              </h1>
              <p className="text-sm text-slate-400">
                Reverse-logistics performance and active return monitoring.
              </p>
            </div>
          </div>
          {/* Batch-dispatch RTO_QUEUED returns to a fulfillment hub (Req 16). */}
          <DispatchButton disabled={loading} onDispatched={handleDispatched} />
        </header>

        <section className="mt-6" aria-label="Key performance indicators">
          {loading ? (
            <p className="text-sm text-slate-400">Loading metrics…</p>
          ) : error ? (
            <div
              role="alert"
              className="rounded-lg border border-red-800 bg-red-950/40 p-3 text-sm text-red-300"
            >
              {error}
            </div>
          ) : metrics ? (
            <KPIGrid metrics={metrics} />
          ) : null}
        </section>

        {/* Active returns operations table with status filter (Req 14, 15). */}
        <section className="mt-8" aria-label="Active returns operations table">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-base font-semibold text-white">Active Returns</h2>
            <StatusFilter
              value={statusFilter}
              onChange={setStatusFilter}
              disabled={rowsLoading}
            />
          </div>
          <OperationsDataTable
            rows={rows}
            loading={rowsLoading}
            error={rowsError}
          />
        </section>
      </div>
    </div>
  );
}
