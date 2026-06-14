import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { NotificationPoller } from "../NotificationPoller";
import { AuthSessionProvider, type AuthUser } from "@/context/AuthSessionContext";
import {
  LOCAL_DEAL_HEADLINE,
  type MatchNotification,
} from "@/lib/notifications";

/**
 * Unit tests for the global notification poller (Requirements 8.3, 8.4, 8.5,
 * and the Flow 18 delayed-match demo: Requirements 18.1–18.4).
 *
 * The poller is wrapped in {@link AuthSessionProvider} and exercised against a
 * stateful fake backend installed on `global.fetch` (the `lib/api` client uses
 * `fetch` with `credentials: "include"`). The backend serves:
 *  - `GET  /api/auth/session`            → the logged-in buyer (Rahul)
 *  - `GET  /api/notifications`           → the current PENDING notifications
 *  - `POST /api/matches/{id}/accept`     → clears the notification (Claim Deal)
 *  - `POST /api/matches/{id}/reject`     → clears the notification (Keep Original)
 *
 * Polling is keyed off the active user and runs an immediate first poll on
 * login, then every `pollIntervalMs` (default 3s, Req 8.1). Tests that assert
 * the 3s cadence use Vitest fake timers; the rest rely on real timers + the
 * immediate first poll.
 */

const RAHUL: AuthUser = {
  user_id: 2,
  name: "Rahul Verma",
  role: "Buyer",
  can_sell: false,
};

/** A representative PENDING notification for the Sony headphones (Flow 18). */
function sonyNotification(): MatchNotification {
  return {
    candidate_id: 77,
    headline: LOCAL_DEAL_HEADLINE,
    money_saved: 450,
    delivery_time_saved_hours: 36,
    carbon_avoided_kg: 2.5,
    distance_km: 3.2,
    product: {
      name: "Sony WH-CH520 Wireless Headphones",
      asin: "B09ZS3R8D2",
      image_url: "https://example.com/sony.jpg",
      uploaded_image_path: null,
    },
  };
}

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

interface BackendOptions {
  /** Whether a session exists; when false the session endpoint returns 401. */
  loggedIn?: boolean;
  /**
   * Notification feed behavior. Either a fixed array returned on every poll, or
   * a function mapping the 1-based poll call count to the array to return (used
   * for the Flow 18 sequencing: first [] then one notification).
   */
  feed?:
    | MatchNotification[]
    | ((pollCallCount: number) => MatchNotification[]);
}

/**
 * Install a stateful fake backend on `global.fetch`. Returns the mock and a
 * `posted` array recording accept/reject POST paths so tests can assert which
 * lifecycle endpoint fired.
 */
function setupBackend(options: BackendOptions = {}) {
  const { loggedIn = true, feed = [] } = options;

  let current: MatchNotification[] = Array.isArray(feed) ? [...feed] : [];
  let pollCount = 0;
  const posted: string[] = [];

  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const url = typeof input === "string" ? input : input.toString();
      const path = new URL(url).pathname;
      const method = (init?.method ?? "GET").toUpperCase();

      if (path === "/api/auth/session" && method === "GET") {
        return loggedIn
          ? jsonResponse(RAHUL, 200)
          : jsonResponse(
              { error: { code: "NO_SESSION", message: "no session" } },
              401,
            );
      }

      if (path === "/api/notifications" && method === "GET") {
        pollCount += 1;
        const items =
          typeof feed === "function" ? feed(pollCount) : current;
        return jsonResponse(items, 200);
      }

      const acceptMatch = path.match(/^\/api\/matches\/(\d+)\/accept$/);
      const rejectMatch = path.match(/^\/api\/matches\/(\d+)\/reject$/);
      if ((acceptMatch || rejectMatch) && method === "POST") {
        posted.push(path);
        // The candidate leaves PENDING, so subsequent polls return nothing.
        current = [];
        return new Response(null, { status: 204 });
      }

      return jsonResponse({ error: { code: "NOT_FOUND", message: path } }, 404);
    },
  );

  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, posted, pollCalls: () => pollCount };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("NotificationPoller — no pending candidate (Req 8.3)", () => {
  it("renders nothing when the feed is empty", async () => {
    const { pollCalls } = setupBackend({ feed: [] });

    render(
      <AuthSessionProvider>
        <NotificationPoller />
      </AuthSessionProvider>,
    );

    // Wait until at least one poll has completed.
    await waitFor(() => expect(pollCalls()).toBeGreaterThanOrEqual(1));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("does not poll while signed out", async () => {
    const { pollCalls } = setupBackend({ loggedIn: false, feed: [sonyNotification()] });

    render(
      <AuthSessionProvider>
        <NotificationPoller />
      </AuthSessionProvider>,
    );

    // Give the provider time to resolve the (absent) session.
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    // No session ⇒ the notifications endpoint is never hit.
    expect(pollCalls()).toBe(0);
  });
});

describe("NotificationPoller — claim hides the popup and accepts (Req 8.4)", () => {
  it("hides the popup immediately and POSTs to the accept endpoint", async () => {
    const user = userEvent.setup();
    const { posted } = setupBackend({ feed: [sonyNotification()] });

    render(
      <AuthSessionProvider>
        <NotificationPoller />
      </AuthSessionProvider>,
    );

    // The immediate first poll surfaces the popup.
    await screen.findByRole("dialog");

    await user.click(screen.getByRole("button", { name: "Claim Deal" }));

    // Popup hides (optimistically within 1s) and stays gone after the re-poll.
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(posted).toContain("/api/matches/77/accept");
  });
});

describe("NotificationPoller — keep original hides the popup and rejects (Req 8.5)", () => {
  it("hides the popup immediately and POSTs to the reject endpoint", async () => {
    const user = userEvent.setup();
    const { posted } = setupBackend({ feed: [sonyNotification()] });

    render(
      <AuthSessionProvider>
        <NotificationPoller />
      </AuthSessionProvider>,
    );

    await screen.findByRole("dialog");

    await user.click(
      screen.getByRole("button", { name: /Keep Original Delivery/ }),
    );

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(posted).toContain("/api/matches/77/reject");
  });
});

describe("NotificationPoller — Flow 18 delayed match demo (Req 18.1–18.4)", () => {
  it("surfaces the '🔥 Local Open-Box Deal' popup on the next 3s poll after the cart-add", async () => {
    vi.useFakeTimers();

    // Req 18.1/18.2: the first poll finds no candidate (no demand yet), then the
    // buyer's in-radius cart-add creates exactly one PENDING candidate that the
    // subsequent poll surfaces.
    const { pollCalls } = setupBackend({
      feed: (call) => (call >= 2 ? [sonyNotification()] : []),
    });

    render(
      <AuthSessionProvider>
        <NotificationPoller pollIntervalMs={3000} />
      </AuthSessionProvider>,
    );

    // Flush session hydration + the immediate first poll (returns []).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(pollCalls()).toBe(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    // Advance the 3s cadence: the next poll returns the PENDING candidate and
    // the popup appears within the 3s bound (Req 18.3).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(pollCalls()).toBeGreaterThanOrEqual(2);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: LOCAL_DEAL_HEADLINE }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Sony WH-CH520 Wireless Headphones"),
    ).toBeInTheDocument();
  });

  it("shows no notification when the buyer is outside the match radius (Req 18.4)", async () => {
    vi.useFakeTimers();

    // Out-of-radius cart-add ⇒ no MatchCandidate ⇒ the feed stays empty.
    const { pollCalls } = setupBackend({ feed: [] });

    render(
      <AuthSessionProvider>
        <NotificationPoller pollIntervalMs={3000} />
      </AuthSessionProvider>,
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(pollCalls()).toBeGreaterThanOrEqual(2);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
