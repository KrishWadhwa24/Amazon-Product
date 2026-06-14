"use client";

/**
 * Admin KPI grid (Requirements 13.2, 13.4, 17.3).
 *
 * Renders the four operations KPIs returned by `GET /api/admin/metrics` as a
 * responsive four-column grid of dark cards designed for the slate-950 admin
 * shell. Each card carries a Lucide icon, a label, and a formatted value:
 *
 *   1. Cache Storage Capacity — a progress bar showing the used-to-total
 *      percentage plus the raw used/total counts (e.g. "82% — 410/500").
 *   2. Reverse Logistics Saved — ₹ currency with two decimals.
 *   3. Carbon Offset Index — kg CO2 with one decimal.
 *   4. NGO CSR Credits — ₹ currency with two decimals.
 *
 * Zero values render explicitly as "0" / "0.00" / "0.0" — never blank
 * (Requirement 13.4).
 */
import {
  Database,
  IndianRupee,
  Leaf,
  HeartHandshake,
  type LucideIcon,
} from "lucide-react";

/** Shape of the payload returned by `GET /api/admin/metrics` (task 23.1). */
export interface AdminMetrics {
  /** Count of items currently in cache/micro-warehouse storage (0..total). */
  cache_used: number;
  /** Total cache storage capacity (>= 1). */
  cache_total: number;
  /** Reverse logistics cost avoided, ₹ (non-negative). */
  reverse_logistics_saved: number;
  /** Carbon offset index, kg CO2 (non-negative). */
  carbon_offset_index_kg: number;
  /** NGO CSR credits accrued, ₹ (non-negative). */
  ngo_csr_credits: number;
}

export interface KPIGridProps {
  /** Metrics to render. */
  metrics: AdminMetrics;
}

const currency = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** Format a ₹ currency value with exactly two decimals (0 -> "₹0.00"). */
function formatCurrency(value: number): string {
  const safe = Number.isFinite(value) ? value : 0;
  return currency.format(safe);
}

/** Format a kg CO2 value with exactly one decimal (0 -> "0.0"). */
function formatKg(value: number): string {
  const safe = Number.isFinite(value) ? value : 0;
  return safe.toFixed(1);
}

/**
 * Compute the used-to-total percentage as a whole number, guarding against a
 * non-positive total. Zero used renders as 0 (Req 13.4).
 */
function usedPercent(used: number, total: number): number {
  if (!Number.isFinite(total) || total <= 0) return 0;
  const pct = Math.round((used / total) * 100);
  return Math.min(100, Math.max(0, pct));
}

/** Shared dark KPI card wrapper for the slate-950 shell. */
function KpiCard({
  icon: Icon,
  label,
  accent,
  children,
}: {
  icon: LucideIcon;
  label: string;
  accent: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col rounded-lg border border-slate-800 bg-slate-900 p-4 shadow-sm">
      <div className="flex items-center gap-2">
        <span
          className={`inline-flex h-8 w-8 items-center justify-center rounded-md bg-slate-800 ${accent}`}
        >
          <Icon className="h-4 w-4" aria-hidden="true" />
        </span>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          {label}
        </h3>
      </div>
      <div className="mt-3">{children}</div>
    </div>
  );
}

/** Cache Storage Capacity card with a progress bar (Req 13.2). */
function CacheCapacityCard({ used, total }: { used: number; total: number }) {
  const pct = usedPercent(used, total);
  return (
    <KpiCard icon={Database} label="Cache Storage Capacity" accent="text-amazonOrange">
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-bold text-white">{pct}%</span>
        <span className="text-sm text-slate-400">
          — {used}/{total}
        </span>
      </div>
      <div
        className="mt-3 h-2 w-full overflow-hidden rounded-full bg-slate-800"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Cache storage capacity used"
      >
        <div
          className="h-full rounded-full bg-amazonOrange transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
    </KpiCard>
  );
}

/** A KPI card that displays a single formatted scalar value. */
function ValueCard({
  icon,
  label,
  accent,
  value,
  unit,
}: {
  icon: LucideIcon;
  label: string;
  accent: string;
  value: string;
  unit?: string;
}) {
  return (
    <KpiCard icon={icon} label={label} accent={accent}>
      <p className="flex items-baseline gap-1">
        <span className="text-2xl font-bold text-white">{value}</span>
        {unit ? <span className="text-sm text-slate-400">{unit}</span> : null}
      </p>
    </KpiCard>
  );
}

/**
 * Four-column responsive KPI grid for the admin operations dashboard.
 */
export function KPIGrid({ metrics }: KPIGridProps) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <CacheCapacityCard used={metrics.cache_used} total={metrics.cache_total} />
      <ValueCard
        icon={IndianRupee}
        label="Reverse Logistics Saved"
        accent="text-emerald-400"
        value={formatCurrency(metrics.reverse_logistics_saved)}
      />
      <ValueCard
        icon={Leaf}
        label="Carbon Offset Index"
        accent="text-green-400"
        value={formatKg(metrics.carbon_offset_index_kg)}
        unit="kg CO₂"
      />
      <ValueCard
        icon={HeartHandshake}
        label="NGO CSR Credits"
        accent="text-sky-400"
        value={formatCurrency(metrics.ngo_csr_credits)}
      />
    </div>
  );
}

export default KPIGrid;
