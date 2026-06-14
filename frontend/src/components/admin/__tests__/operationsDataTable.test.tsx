import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";

import {
  AdminReturnRow,
  OperationsDataTable,
} from "@/components/admin/OperationsDataTable";

/**
 * Unit + snapshot tests for the admin OperationsDataTable (Requirements 14.4,
 * 14.6, 14.7).
 *
 * The table is presentational: the parent page owns fetching and filtering and
 * passes the resulting `rows` down. These tests therefore assert that the table
 * renders exactly the rows it is given (one row per item, with ID, product
 * name + ASIN, source user + location, a status badge, and a Time Remaining
 * cell), surfaces the empty / loading / error states, and matches a snapshot
 * for a populated table.
 */

// Fixed far-future expiry so the LiveCountdownTimer is deterministic in
// snapshots (no danger blink, default color).
const FAR_FUTURE = "2999-01-01T00:00:00.000Z";

const ROWS: AdminReturnRow[] = [
  {
    id: 101,
    status: "SCANNING",
    asin: "B00ABCDEF1",
    product: {
      name: "Sony WH-CH520 Wireless Headphones",
      image_url: "https://example.com/sony.jpg",
      uploaded_image_path: null,
    },
    source: {
      user_name: "Asha Verma",
      latitude: 12.9716,
      longitude: 77.5946,
    },
    initiated_at: "2024-01-01T00:00:00.000Z",
    expires_at: FAR_FUTURE,
  },
  {
    id: 102,
    status: "NGO_ROUTING",
    asin: "B00ZYXWVU2",
    product: {
      name: "Instant Pot Duo 7-in-1",
      image_url: null,
      uploaded_image_path: "/uploads/instantpot.jpg",
    },
    source: {
      user_name: "Liam Chen",
      latitude: 19.076,
      longitude: 72.8777,
    },
    initiated_at: "2024-01-02T00:00:00.000Z",
    expires_at: FAR_FUTURE,
  },
];

describe("OperationsDataTable — columns & rows (Req 14.4)", () => {
  it("renders one row per item with all column data", () => {
    render(<OperationsDataTable rows={ROWS} />);

    // One data row per item (plus the header row).
    const bodyRows = screen.getAllByRole("row").filter((r) =>
      within(r).queryAllByRole("cell").length > 0,
    );
    expect(bodyRows).toHaveLength(ROWS.length);

    // IDs.
    expect(screen.getByText("101")).toBeInTheDocument();
    expect(screen.getByText("102")).toBeInTheDocument();

    // Product names + ASINs.
    expect(
      screen.getByText("Sony WH-CH520 Wireless Headphones"),
    ).toBeInTheDocument();
    expect(screen.getByText("B00ABCDEF1")).toBeInTheDocument();
    expect(screen.getByText("Instant Pot Duo 7-in-1")).toBeInTheDocument();
    expect(screen.getByText("B00ZYXWVU2")).toBeInTheDocument();

    // Source user + formatted location.
    expect(screen.getByText("Asha Verma")).toBeInTheDocument();
    expect(screen.getByText("12.9716, 77.5946")).toBeInTheDocument();
    expect(screen.getByText("Liam Chen")).toBeInTheDocument();
    expect(screen.getByText("19.0760, 72.8777")).toBeInTheDocument();
  });

  it("renders a status badge carrying data-status for each row", () => {
    const { container } = render(<OperationsDataTable rows={ROWS} />);
    expect(
      container.querySelector('[data-status="SCANNING"]'),
    ).toBeInTheDocument();
    expect(
      container.querySelector('[data-status="NGO_ROUTING"]'),
    ).toBeInTheDocument();
  });

  it("renders a Time Remaining countdown cell per row", () => {
    const { container } = render(<OperationsDataTable rows={ROWS} />);
    // LiveCountdownTimer renders a span with data-danger.
    const timers = container.querySelectorAll("[data-danger]");
    expect(timers).toHaveLength(ROWS.length);
  });

  it("renders the Time Remaining column header", () => {
    render(<OperationsDataTable rows={ROWS} />);
    expect(
      screen.getByRole("columnheader", { name: /time remaining/i }),
    ).toBeInTheDocument();
  });
});

describe("OperationsDataTable — props-driven filtering reflection (Req 14.6, 14.7)", () => {
  it("renders exactly the rows passed in (the page owns refetch/filtering)", () => {
    const filtered = [ROWS[1]]; // simulate a status filter that matched one row
    render(<OperationsDataTable rows={filtered} />);

    expect(screen.getByText("Instant Pot Duo 7-in-1")).toBeInTheDocument();
    expect(
      screen.queryByText("Sony WH-CH520 Wireless Headphones"),
    ).not.toBeInTheDocument();

    const bodyRows = screen.getAllByRole("row").filter((r) =>
      within(r).queryAllByRole("cell").length > 0,
    );
    expect(bodyRows).toHaveLength(1);
  });
});

describe("OperationsDataTable — empty / loading / error states (Req 14.4)", () => {
  it("shows the empty-state message when no rows match", () => {
    render(<OperationsDataTable rows={[]} />);
    expect(
      screen.getByText("No returns match the selected filter."),
    ).toBeInTheDocument();
  });

  it("shows a loading row while a fetch is in flight", () => {
    render(<OperationsDataTable rows={[]} loading />);
    expect(screen.getByText(/loading returns/i)).toBeInTheDocument();
    expect(
      screen.queryByText("No returns match the selected filter."),
    ).not.toBeInTheDocument();
  });

  it("shows an error alert instead of the table body when error is set", () => {
    render(<OperationsDataTable rows={[]} error="Failed to load returns" />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Failed to load returns");
    expect(
      screen.queryByText("No returns match the selected filter."),
    ).not.toBeInTheDocument();
  });
});

describe("OperationsDataTable — snapshot", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("matches the snapshot for a populated table", () => {
    // Fix the clock so the LiveCountdownTimer renders a deterministic value.
    // With "now" frozen and a far-future expiry the countdown is stable.
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2024-06-01T00:00:00.000Z"));

    const { container } = render(<OperationsDataTable rows={ROWS} />);
    expect(container).toMatchSnapshot();
  });
});
