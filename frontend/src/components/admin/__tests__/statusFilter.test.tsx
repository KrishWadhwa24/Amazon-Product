import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import {
  STATUS_FILTER_OPTIONS,
  StatusFilter,
  toStatusQueryParam,
} from "@/components/admin/StatusFilter";

/**
 * Unit tests for the admin StatusFilter dropdown (Requirements 14.3, 14.5).
 *
 * Confirms the dropdown exposes exactly the five required options (in order),
 * emits the selected value via onChange, and that the "All" display value maps
 * to the backend `ALL` sentinel query parameter (Req 14.7 / alias mapping).
 */

const EXPECTED_OPTIONS = [
  "All",
  "SCANNING",
  "CACHED",
  "RTO_QUEUED",
  "NGO_QUEUED",
] as const;

describe("StatusFilter — options (Req 14.5)", () => {
  it("exports exactly the five ordered filter options", () => {
    expect([...STATUS_FILTER_OPTIONS]).toEqual([...EXPECTED_OPTIONS]);
  });

  it("renders exactly the five options in order", () => {
    render(<StatusFilter value="All" onChange={() => {}} />);

    const select = screen.getByLabelText(
      /filter returns by status/i,
    ) as HTMLSelectElement;
    const optionValues = Array.from(select.options).map((o) => o.value);
    const optionLabels = Array.from(select.options).map((o) => o.textContent);

    expect(optionValues).toEqual([...EXPECTED_OPTIONS]);
    expect(optionLabels).toEqual([...EXPECTED_OPTIONS]);
    expect(select.options).toHaveLength(5);
  });

  it("reflects the controlled value", () => {
    render(<StatusFilter value="RTO_QUEUED" onChange={() => {}} />);
    const select = screen.getByLabelText(
      /filter returns by status/i,
    ) as HTMLSelectElement;
    expect(select.value).toBe("RTO_QUEUED");
  });
});

describe("StatusFilter — onChange (Req 14.6)", () => {
  it("calls onChange with the selected value", () => {
    const onChange = vi.fn();
    render(<StatusFilter value="All" onChange={onChange} />);

    const select = screen.getByLabelText(/filter returns by status/i);
    fireEvent.change(select, { target: { value: "NGO_QUEUED" } });

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("NGO_QUEUED");
  });

  it("does not call onChange while disabled is irrelevant — fires for each distinct option", () => {
    const onChange = vi.fn();
    render(<StatusFilter value="All" onChange={onChange} />);
    const select = screen.getByLabelText(/filter returns by status/i);

    fireEvent.change(select, { target: { value: "SCANNING" } });
    fireEvent.change(select, { target: { value: "CACHED" } });

    expect(onChange).toHaveBeenNthCalledWith(1, "SCANNING");
    expect(onChange).toHaveBeenNthCalledWith(2, "CACHED");
  });
});

describe("toStatusQueryParam — alias mapping (Req 14.3, 14.7)", () => {
  it('maps "All" to the ALL sentinel', () => {
    expect(toStatusQueryParam("All")).toBe("ALL");
  });

  it("passes every concrete status through unchanged", () => {
    expect(toStatusQueryParam("SCANNING")).toBe("SCANNING");
    expect(toStatusQueryParam("CACHED")).toBe("CACHED");
    expect(toStatusQueryParam("RTO_QUEUED")).toBe("RTO_QUEUED");
    expect(toStatusQueryParam("NGO_QUEUED")).toBe("NGO_QUEUED");
  });
});
