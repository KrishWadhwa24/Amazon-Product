import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import LocalDealsPage from "../page";
import { AuthSessionProvider } from "@/context/AuthSessionContext";

/**
 * Snapshot + structure tests for the Local Verified Used Deals grid
 * (Requirements 12.4, 12.5, 12.6).
 *
 * The page fetches `GET /api/resale/feed` (a bare array) via `lib/api`, which
 * uses the global `fetch`. We stub `fetch` to return a deterministic feed and
 * use `findBy*` to await the async render.
 *
 * Coverage:
 *  - Populated grid renders the title, the "✅ Amazon Verified Original
 *    Purchase" badge per card (Req 12.6), the "Condition: {grade}" text
 *    (Req 12.6), and is captured in a snapshot (Req 12.4).
 *  - Empty feed still renders the titled grid with an empty-state message and
 *    no error (Req 12.5).
 */

const PAGE_TITLE = "Amazon Local Verified Used Deals";

interface FeedProduct {
  asin: string;
  name: string;
  price: number;
  image_url: string;
  uploaded_image_path: string | null;
}

interface ResaleFeedItem {
  id: number;
  condition_grade: "Like New" | "Good" | "Fair";
  resale_price: number;
  status: string;
  listed_at: string;
  condition_image_url: string;
  original_purchased_at: string;
  product: FeedProduct;
}

const SAMPLE_FEED: ResaleFeedItem[] = [
  {
    id: 1,
    condition_grade: "Like New",
    resale_price: 3499.0,
    status: "ACTIVE",
    listed_at: "2024-05-02T10:00:00Z",
    condition_image_url: "https://example.com/condition-1.jpg",
    original_purchased_at: "2024-01-15T08:30:00Z",
    product: {
      asin: "B0SONY520",
      name: "Sony WH-CH520 Wireless Headphones",
      price: 4499.0,
      image_url: "https://example.com/official-1.jpg",
      uploaded_image_path: null,
    },
  },
  {
    id: 2,
    condition_grade: "Good",
    resale_price: 599.0,
    status: "ACTIVE",
    listed_at: "2024-05-01T09:00:00Z",
    condition_image_url: "https://example.com/condition-2.jpg",
    original_purchased_at: "2024-02-20T12:00:00Z",
    product: {
      asin: "B0LEVIS01",
      name: "Levi's T-Shirt",
      price: 999.0,
      image_url: "https://example.com/official-2.jpg",
      uploaded_image_path: null,
    },
  },
];

/**
 * Stub the global fetch to return the given resale feed payload. The auth
 * session endpoint resolves to 401 (signed out) so the page shows the
 * "Sign in to buy" affordance deterministically; the feed endpoint returns the
 * provided payload (a bare array).
 */
function stubFeed(payload: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/api/auth/session")) {
        return new Response(
          JSON.stringify({ error: { code: "NO_SESSION", message: "no session" } }),
          { status: 401, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

/** Render the page wrapped in the auth session provider it now depends on. */
function renderPage() {
  return render(
    <AuthSessionProvider>
      <LocalDealsPage />
    </AuthSessionProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("LocalDealsPage — populated grid (Req 12.4, 12.6)", () => {
  it("renders the verified badge, condition grade, and matches a snapshot", async () => {
    stubFeed(SAMPLE_FEED);

    const { container } = renderPage();

    // Title renders (Req 12.4).
    await screen.findByText(PAGE_TITLE);

    // Wait for the async feed to populate the grid.
    await screen.findByText("Sony WH-CH520 Wireless Headphones");
    expect(screen.getByText("Levi's T-Shirt")).toBeInTheDocument();

    // Each card shows the "Amazon Verified Original Purchase" badge (Req 12.6).
    const verifiedBadges = screen.getAllByText(
      /Amazon Verified Original Purchase/i,
    );
    expect(verifiedBadges).toHaveLength(SAMPLE_FEED.length);

    // Each card shows its "Condition: {grade}" text (Req 12.6).
    expect(screen.getByText(/Condition:\s*Like New/i)).toBeInTheDocument();
    expect(screen.getByText(/Condition:\s*Good/i)).toBeInTheDocument();

    // Snapshot the populated grid.
    expect(container).toMatchSnapshot();
  });
});

describe("LocalDealsPage — empty state (Req 12.5)", () => {
  it("renders the title and an empty-state message with no error", async () => {
    stubFeed([]);

    const { container } = renderPage();

    // The titled grid still renders (Req 12.5).
    await screen.findByText(PAGE_TITLE);

    // An empty-state message is shown rather than an error.
    await screen.findByText(/No local deals available yet/i);
    expect(screen.queryByRole("alert")).toBeNull();

    // No deal cards rendered.
    expect(
      screen.queryByText(/Amazon Verified Original Purchase/i),
    ).toBeNull();

    expect(container).toMatchSnapshot();
  });
});
