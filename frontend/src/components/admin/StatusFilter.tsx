"use client";

/**
 * Admin status filter dropdown (Requirement 14.5).
 *
 * Renders a `<select>` containing exactly the options All, SCANNING, CACHED,
 * RTO_QUEUED, and NGO_QUEUED. Selecting an option invokes `onChange` with the
 * chosen value. The parent (the operations page) translates the value into the
 * `GET /api/admin/returns?status=...` query and refetches (Req 14.6, 14.7).
 *
 * The CACHED / RTO_QUEUED / NGO_QUEUED values are presentation aliases that the
 * backend maps to MICROWAREHOUSE / EXPIRED / NGO_ROUTING respectively (task
 * 24.1); "All" is sent to the backend as the `ALL` sentinel.
 */
import { Filter } from "lucide-react";

/** The exact, ordered set of status filter options (Req 14.5). */
export const STATUS_FILTER_OPTIONS = [
  "All",
  "SCANNING",
  "CACHED",
  "RTO_QUEUED",
  "NGO_QUEUED",
] as const;

/** A value the {@link StatusFilter} can emit. */
export type StatusFilterValue = (typeof STATUS_FILTER_OPTIONS)[number];

export interface StatusFilterProps {
  /** Currently selected filter value. */
  value: StatusFilterValue;
  /** Called with the newly selected filter value. */
  onChange: (value: StatusFilterValue) => void;
  /** Optional wrapper classes. */
  className?: string;
  /** Disables the control while a refetch is in flight. */
  disabled?: boolean;
}

/**
 * Map a {@link StatusFilterValue} to the `status` query parameter the backend
 * expects (Req 14.7): "All" becomes the `ALL` sentinel; every other value is
 * passed through unchanged.
 */
export function toStatusQueryParam(value: StatusFilterValue): string {
  return value === "All" ? "ALL" : value;
}

/**
 * Dark-mode status filter dropdown for the operations table.
 */
export function StatusFilter({
  value,
  onChange,
  className = "",
  disabled = false,
}: StatusFilterProps) {
  return (
    <label className={`inline-flex items-center gap-2 ${className}`.trim()}>
      <span className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-400">
        <Filter className="h-4 w-4" aria-hidden="true" />
        Status
      </span>
      <select
        aria-label="Filter returns by status"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value as StatusFilterValue)}
        className="rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-slate-100 shadow-sm focus:border-amazonOrange focus:outline-none focus:ring-1 focus:ring-amazonOrange disabled:cursor-not-allowed disabled:opacity-60"
      >
        {STATUS_FILTER_OPTIONS.map((option) => (
          <option key={option} value={option} className="bg-slate-900 text-slate-100">
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

export default StatusFilter;
