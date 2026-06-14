"use client";

/**
 * Admin KPI grid (Requirements 13.2, 13.4, 17.3).
 *
 * Renders the operations KPIs returned by `GET /api/admin/metrics` as a
 * responsive grid of dark cards designed for the slate-950 admin shell.
 *
 * Row 1 — platform metrics (4 cards):
 *   1. Cache Storage Capacity — progress bar (used/total %).
 *   2. Reverse Logistics Saved — ₹ currency.
 *   3. Carbon Offset Index — kg CO₂.
 *   4. NGO CSR Credits — ₹ currency.
 *
 * Row 2 — profit tracker (3 cards, Feature 1-3):
 *   5. Resale Commission Earned — ₹50 × SOLD resale listings (Feature 1).
 *   6. Tax Credits Accrued — value deducted on NGO dispatch (Feature 2).  [placeholder shown, populated by Feature 2]
 *   7. Logistics Savings — 10% of product value on local matches (Feature 3). [placeholder shown, populated by Feature 3]
 *
 * Zero values render explicitly — never blank (Requirement 13.4).
 */
import {
  Database,
  IndianRupee,
  Leaf,
  HeartHandshake,
  BadgeDollarSign,
  Receipt,
  TrendingDown,
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
  /** Feature 1: ₹50 × count of SOLD resale listings (non-negative). */
  resale_commission_earned: number;
  /** Feature 2: sum of item values deducted on NGO dispatch (non-negative). */
  tax_credits_accrued: number;
  /** Feature 3: 10% × product price for each LOCAL_DELIVERY match (non-negative). */
  logistics_savings: number;
}

export interface KPIGridProps {
  metrics: AdminMetrics;
}

const currency = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatCurrency(value: number): string {
  const safe = Number.isFinite(value) ? value : 0;
  return currency.format(safe);
}

function formatKg(value: number): string {
  const safe = Number.isFinite(value) ? value : 0;
  return safe.toFixed(1);
}

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

function CacheCapacityCard({ used, total }: { used: number; total: number }) {
  const pct = usedPercent(used, total);
  return (
    <KpiCard icon={Database} label="Cache Storage Capacity" accent="text-amazonOrange">
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-bold text-white">{pct}%</span>
        <span className="text-sm text-slate-400">— {used}/{total}</span>
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

function ValueCard({
  icon,
  label,
  accent,
  value,
  unit,
  sublabel,
}: {
  icon: LucideIcon;
  label: string;
  accent: string;
  value: string;
  unit?: string;
  sublabel?: string;
}) {
  return (
    <KpiCard icon={icon} label={label} accent={accent}>
      <p className="flex items-baseline gap-1">
        <span className="text-2xl font-bold text-white">{value}</span>
        {unit ? <span className="text-sm text-slate-400">{unit}</span> : null}
      </p>
      {sublabel ? (
        <p className="mt-1 text-xs text-slate-500">{sublabel}</p>
      ) : null}
    </KpiCard>
  );
}

/**
 * Responsive KPI grid for the admin operations dashboard.
 *
 * Platform metrics row (4 cols) + Profit tracker row (3 cols, Feature 1-3).
 */
export function KPIGrid({ metrics }: KPIGridProps) {
  return (
    <div className="space-y-4">
      {/* ── Row 1: Platform metrics ── */}
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

      {/* ── Row 2: Profit tracker (Features 1-3) ── */}
      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Profit Tracker
        </p>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <ValueCard
            icon={BadgeDollarSign}
            label="Resale Commission Earned"
            accent="text-amber-400"
            value={formatCurrency(metrics.resale_commission_earned)}
            sublabel="₹50 per sold resale listing"
          />
          <ValueCard
            icon={Receipt}
            label="Tax Credits Accrued"
            accent="text-violet-400"
            value={formatCurrency(metrics.tax_credits_accrued)}
            sublabel="Value deducted on NGO dispatch"
          />
          <ValueCard
            icon={TrendingDown}
            label="Logistics Savings (Zero-Mile)"
            accent="text-teal-400"
            value={formatCurrency(metrics.logistics_savings)}
            sublabel="10% of value saved per local match"
          />
        </div>
      </div>
    </div>
  );
}

export default KPIGrid;
