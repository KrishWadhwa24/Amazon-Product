"use client";

/**
 * Admin operations data table (Requirement 14.4).
 *
 * Renders the active returns returned by `GET /api/admin/returns` as a dark
 * table sized for the slate-950 operations shell. Columns (Req 14.4):
 *
 *   - ID          — the ReturnOrder id.
 *   - Product     — a {@link ProductImage} thumbnail plus the ASIN.
 *   - Source      — the seller's name and lat/lon location.
 *   - Status      — a styled badge per status.
 *   - Time Remaining — a {@link LiveCountdownTimer} driven by `expires_at`.
 *   - Actions     — placeholder cell; the DispatchButton lands in task 24.6.
 *
 * The component is presentational: the parent page owns fetching and filtering
 * (Req 14.6, 14.7) and passes the resulting `rows` down. Loading, error, and
 * empty states are handled here so the table is self-contained.
 */
import { LiveCountdownTimer } from "@/components/admin/LiveCountdownTimer";
import { ProductImage } from "@/components/ProductImage";

/** Product fields joined into each admin returns row. */
export interface AdminReturnProduct {
  name: string;
  image_url: string | null;
  uploaded_image_path: string | null;
}

/** Seller/source fields joined into each admin returns row. */
export interface AdminReturnSource {
  user_name: string;
  latitude: number;
  longitude: number;
}

/**
 * A single row from `GET /api/admin/returns` (task 24.1), joined with its
 * Product and User.
 */
export interface AdminReturnRow {
  id: number | string;
  status: string;
  asin: string;
  product: AdminReturnProduct;
  source: AdminReturnSource;
  initiated_at: string;
  expires_at: string;
}

export interface OperationsDataTableProps {
  /** Rows to render (already filtered by the parent). */
  rows: AdminReturnRow[];
  /** Show a loading row while a fetch is in flight. */
  loading?: boolean;
  /** Error message to surface instead of the table body, when set. */
  error?: string | null;
}

/** Tailwind classes for each status badge; unknown statuses fall back. */
const STATUS_BADGE_CLASSES: Record<string, string> = {
  SCANNING: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  MATCH_FOUND: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  BUYER_ACCEPTED: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  LOCAL_DELIVERY: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  EXPIRED: "bg-red-500/15 text-red-300 ring-red-500/30",
  NGO_ROUTING: "bg-violet-500/15 text-violet-300 ring-violet-500/30",
  MICROWAREHOUSE: "bg-indigo-500/15 text-indigo-300 ring-indigo-500/30",
  FC_TRANSIT: "bg-slate-500/15 text-slate-300 ring-slate-500/30",
};

const STATUS_BADGE_FALLBACK = "bg-slate-500/15 text-slate-300 ring-slate-500/30";

/** Styled status badge cell (Req 14.4). */
function StatusBadge({ status }: { status: string }) {
  const classes = STATUS_BADGE_CLASSES[status] ?? STATUS_BADGE_FALLBACK;
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${classes}`}
      data-status={status}
    >
      {status}
    </span>
  );
}

/** Format a lat/lon pair compactly for the Source column. */
function formatLocation(lat: number, lon: number): string {
  const fmt = (n: number) => (Number.isFinite(n) ? n.toFixed(4) : "—");
  return `${fmt(lat)}, ${fmt(lon)}`;
}

const COLUMN_COUNT = 6;

/**
 * Dark operations data table for the admin dashboard.
 */
export function OperationsDataTable({
  rows,
  loading = false,
  error = null,
}: OperationsDataTableProps) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-900/60">
      <table className="min-w-full divide-y divide-slate-800 text-left text-sm">
        <thead className="bg-slate-900/80">
          <tr className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            <th scope="col" className="px-4 py-3">ID</th>
            <th scope="col" className="px-4 py-3">Product</th>
            <th scope="col" className="px-4 py-3">Source</th>
            <th scope="col" className="px-4 py-3">Status</th>
            <th scope="col" className="px-4 py-3">Time Remaining</th>
            <th scope="col" className="px-4 py-3">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/70 text-slate-200">
          {loading ? (
            <tr>
              <td colSpan={COLUMN_COUNT} className="px-4 py-8 text-center text-slate-400">
                Loading returns…
              </td>
            </tr>
          ) : error ? (
            <tr>
              <td colSpan={COLUMN_COUNT} className="px-4 py-8 text-center">
                <span role="alert" className="text-red-300">
                  {error}
                </span>
              </td>
            </tr>
          ) : rows.length === 0 ? (
            <tr>
              <td colSpan={COLUMN_COUNT} className="px-4 py-8 text-center text-slate-500">
                No returns match the selected filter.
              </td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr key={row.id} className="hover:bg-slate-800/40">
                <td className="whitespace-nowrap px-4 py-3 font-mono text-slate-400">
                  {row.id}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-3">
                    <ProductImage
                      src={row.product.uploaded_image_path ?? row.product.image_url}
                      alt={row.product.name}
                      className="h-10 w-10 flex-shrink-0"
                    />
                    <div className="min-w-0">
                      <p className="truncate font-medium text-slate-100">
                        {row.product.name}
                      </p>
                      <p className="truncate font-mono text-xs text-slate-400">
                        {row.asin}
                      </p>
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <p className="font-medium text-slate-100">{row.source.user_name}</p>
                  <p className="font-mono text-xs text-slate-400">
                    {formatLocation(row.source.latitude, row.source.longitude)}
                  </p>
                </td>
                <td className="px-4 py-3">
                  <StatusBadge status={row.status} />
                </td>
                <td className="whitespace-nowrap px-4 py-3">
                  <LiveCountdownTimer expiresAt={row.expires_at} />
                </td>
                <td className="px-4 py-3">
                  {/* Placeholder — the DispatchButton wiring is task 24.6. */}
                  <span className="text-xs text-slate-500">—</span>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export default OperationsDataTable;
