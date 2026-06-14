import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";

import { KPIGrid, type AdminMetrics } from "../KPIGrid";

/**
 * Unit + snapshot tests for the admin KPIGrid component
 * (Requirements 13.2, 13.4, 17.3).
 *
 * The component is rendered directly with fixed metrics so these tests stay
 * decoupled from the `/admin/operations` page wiring. Coverage:
 *  - Populated metrics: all four KPI labels render, the cache progress bar
 *    reports the correct percentage + "used/total", and the currency / kg
 *    values are formatted with the expected decimals (Req 13.2).
 *  - Zero metrics: values render explicitly as "0" / "₹0.00" / "0.0" — never
 *    blank — and the progress bar reports 0% (Req 13.4).
 *  - Dark-mode shell: the KPI cards carry slate-950 dark classes (Req 17.3).
 */

const POPULATED: AdminMetrics = {
  cache_used: 410,
  cache_total: 500,
  reverse_logistics_saved: 142500,
  carbon_offset_index_kg: 1240,
  ngo_csr_credits: 45000,
};

const ZERO: AdminMetrics = {
  cache_used: 0,
  cache_total: 1,
  reverse_logistics_saved: 0,
  carbon_offset_index_kg: 0,
  ngo_csr_credits: 0,
};

/** Matches a ₹ currency string with exactly two decimal places. */
const CURRENCY_2DP = /₹[\d,]+\.\d{2}/;

describe("KPIGrid — populated metrics (Req 13.2)", () => {
  it("renders the four KPI labels", () => {
    render(<KPIGrid metrics={POPULATED} />);

    expect(screen.getByText("Cache Storage Capacity")).toBeInTheDocument();
    expect(screen.getByText("Reverse Logistics Saved")).toBeInTheDocument();
    expect(screen.getByText("Carbon Offset Index")).toBeInTheDocument();
    expect(screen.getByText("NGO CSR Credits")).toBeInTheDocument();
  });

  it("shows the cache progress bar at 82% with the used/total counts", () => {
    render(<KPIGrid metrics={POPULATED} />);

    // 410 / 500 = 82%.
    const progressbar = screen.getByRole("progressbar");
    expect(progressbar).toHaveAttribute("aria-valuenow", "82");
    expect(progressbar).toHaveAttribute("aria-valuemin", "0");
    expect(progressbar).toHaveAttribute("aria-valuemax", "100");

    expect(screen.getByText("82%")).toBeInTheDocument();
    expect(screen.getByText(/410\s*\/\s*500/)).toBeInTheDocument();
  });

  it("formats reverse logistics and NGO credits as ₹ with two decimals", () => {
    render(<KPIGrid metrics={POPULATED} />);

    const currencyValues = screen.getAllByText(CURRENCY_2DP);

    // Both reverse-logistics (142500) and NGO credits (45000) render as ₹ 2dp.
    expect(currencyValues.length).toBeGreaterThanOrEqual(2);

    // Normalize away the ₹ symbol and (Indian) thousands separators so the
    // assertion is independent of grouping style (e.g. "₹1,42,500.00").
    const normalized = currencyValues.map((el) =>
      (el.textContent ?? "").replace(/[₹,\s]/g, ""),
    );
    expect(normalized).toContain("142500.00");
    expect(normalized).toContain("45000.00");

    // Every currency value carries exactly two decimal places.
    normalized.forEach((t) => expect(t).toMatch(/\.\d{2}$/));
  });

  it("formats the carbon offset index in kg with one decimal", () => {
    render(<KPIGrid metrics={POPULATED} />);

    expect(screen.getByText("1240.0")).toBeInTheDocument();
  });

  it("matches the populated grid snapshot", () => {
    const { container } = render(<KPIGrid metrics={POPULATED} />);
    expect(container).toMatchSnapshot();
  });
});

describe("KPIGrid — zero metrics never render blank (Req 13.4)", () => {
  it("renders 0 / ₹0.00 / 0.0 explicitly", () => {
    render(<KPIGrid metrics={ZERO} />);

    // Cache percentage renders "0%" and counts "0/1".
    expect(screen.getByText("0%")).toBeInTheDocument();
    expect(screen.getByText(/0\s*\/\s*1/)).toBeInTheDocument();

    // Currency zeros render as "₹0.00" (both reverse-logistics and NGO).
    const zeroCurrency = screen.getAllByText("₹0.00");
    expect(zeroCurrency).toHaveLength(2);

    // Carbon offset zero renders as "0.0".
    expect(screen.getByText("0.0")).toBeInTheDocument();
  });

  it("reports 0% on the progress bar", () => {
    render(<KPIGrid metrics={ZERO} />);

    const progressbar = screen.getByRole("progressbar");
    expect(progressbar).toHaveAttribute("aria-valuenow", "0");
  });

  it("matches the zero-metrics grid snapshot", () => {
    const { container } = render(<KPIGrid metrics={ZERO} />);
    expect(container).toMatchSnapshot();
  });
});

describe("KPIGrid — dark-mode shell (Req 17.3)", () => {
  it("uses slate-950 dark classes on the KPI cards", () => {
    const { container } = render(<KPIGrid metrics={POPULATED} />);

    // Each KPI card is a dark slate card for the slate-950 admin shell.
    const cards = container.querySelectorAll(".bg-slate-900");
    expect(cards.length).toBe(4);

    cards.forEach((card) => {
      expect(card.className).toContain("bg-slate-900");
      expect(card.className).toContain("border-slate-800");
    });

    // The progress-bar track also uses a dark slate fill.
    const progressbar = within(container as HTMLElement).getByRole(
      "progressbar",
    );
    expect(progressbar.className).toContain("bg-slate-800");
  });
});
