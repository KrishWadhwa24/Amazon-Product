import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import LoginPage from "../page";
import { NavBar } from "@/components/NavBar";
import {
  AuthSessionProvider,
  useAuthSession,
  type AuthUser,
} from "@/context/AuthSessionContext";

/**
 * Unit tests for the login flow and session replacement (Requirement 1).
 *
 * These exercise the AuthSessionProvider + LoginPage + NavBar against a
 * stateful fake backend installed on `global.fetch` (the `lib/api` client uses
 * `fetch` with `credentials: "include"`). `next/navigation`'s `useRouter` is
 * mocked so the post-login redirect can be observed.
 *
 * Coverage:
 *  - Successful login establishes a session and redirects to `/` (Req 1.1, 1.2).
 *  - Failed login shows an authentication-failed alert and does not redirect
 *    (Req 1.3).
 *  - Logout clears the active user so the NavBar reverts to "sign in" (Req 1.6).
 *  - Switching users (logout then login as a different account) replaces the
 *    context user so user-scoped content reflects only the new session (Req 1.7).
 */

// --- next/navigation mock (hoisted so the factory can reference the spy) ---
const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: pushMock,
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
  }),
}));

// --- Seeded demo accounts (mirror seed.py / the login page prefill) ---
interface SeedAccount extends AuthUser {
  email: string;
  password: string;
}

const PRIYA: SeedAccount = {
  user_id: 1,
  name: "Priya Sharma",
  role: "Seller",
  can_sell: true,
  email: "priya.sharma@example.com",
  password: "priya",
};

const RAHUL: SeedAccount = {
  user_id: 2,
  name: "Rahul Verma",
  role: "Buyer",
  can_sell: false,
  email: "rahul.verma@example.com",
  password: "rahul",
};

const ACCOUNTS: readonly SeedAccount[] = [PRIYA, RAHUL];

/** Strip credentials, returning the public AuthUser shape the API exposes. */
function toAuthUser(account: SeedAccount): AuthUser {
  const { user_id, name, role, can_sell } = account;
  return { user_id, name, role, can_sell };
}

/** Build a JSON Response with the given status. */
function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/**
 * Install a stateful fake backend on `global.fetch` that mimics the auth
 * endpoints. The "session" is in-memory and mutated by login/logout so the
 * provider's hydrate/login/logout flows behave end-to-end.
 */
function setupBackend(initialUser: SeedAccount | null) {
  let current: SeedAccount | null = initialUser;

  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const url = typeof input === "string" ? input : input.toString();
      const path = new URL(url).pathname;
      const method = (init?.method ?? "GET").toUpperCase();

      if (path === "/api/auth/session" && method === "GET") {
        return current
          ? jsonResponse(toAuthUser(current), 200)
          : jsonResponse(
              { error: { code: "NO_SESSION", message: "no session" } },
              401,
            );
      }

      if (path === "/api/auth/login" && method === "POST") {
        const body = init?.body
          ? (JSON.parse(init.body as string) as {
              email?: string;
              password?: string;
            })
          : {};
        const match = ACCOUNTS.find(
          (a) => a.email === body.email && a.password === body.password,
        );
        if (!match) {
          return jsonResponse(
            {
              error: {
                code: "AUTH_FAILED",
                message: "Invalid email or password",
              },
            },
            401,
          );
        }
        current = match;
        return jsonResponse(toAuthUser(match), 200);
      }

      if (path === "/api/auth/logout" && method === "POST") {
        current = null;
        return new Response(null, { status: 204 });
      }

      return jsonResponse(
        { error: { code: "NOT_FOUND", message: path } },
        404,
      );
    },
  );

  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** Small consumer that surfaces the active user and triggers session changes. */
function SessionProbe() {
  const { user, login, logout } = useAuthSession();
  return (
    <div>
      <span data-testid="current-user">{user?.name ?? "none"}</span>
      <button type="button" onClick={() => void logout()}>
        probe-logout
      </button>
      <button
        type="button"
        onClick={() => {
          void login(PRIYA.email, PRIYA.password);
        }}
      >
        probe-login-priya
      </button>
    </div>
  );
}

beforeEach(() => {
  pushMock.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("LoginPage — successful login (Req 1.1, 1.2)", () => {
  it("authenticates a seeded account and redirects to the home page", async () => {
    const user = userEvent.setup();
    setupBackend(null);

    render(
      <AuthSessionProvider>
        <LoginPage />
      </AuthSessionProvider>,
    );

    // Prefill the form via the Priya demo account, then submit.
    await user.click(screen.getByRole("button", { name: /Priya Sharma/ }));
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    // Login succeeds → redirect to "/" (Req 1.7 entry point).
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/"));

    // No authentication-failed alert is shown on success.
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("LoginPage — failed login (Req 1.3)", () => {
  it("shows an authentication-failed alert and does not redirect", async () => {
    const user = userEvent.setup();
    setupBackend(null);

    render(
      <AuthSessionProvider>
        <LoginPage />
      </AuthSessionProvider>,
    );

    await user.type(screen.getByLabelText("Email"), PRIYA.email);
    await user.type(screen.getByLabelText("Password"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/authentication failed/i);
    expect(pushMock).not.toHaveBeenCalled();
  });
});

describe("NavBar — logout clears the active user (Req 1.6)", () => {
  it("reverts from the signed-in greeting to the sign-in prompt", async () => {
    const user = userEvent.setup();
    setupBackend(RAHUL);

    render(
      <AuthSessionProvider>
        <NavBar />
      </AuthSessionProvider>,
    );

    // Hydrates to the logged-in session (Req 1.4).
    await screen.findByText(/Hello, Rahul/);

    await user.click(screen.getByRole("button", { name: /sign out/i }));

    // After logout the account area shows the signed-out prompt (Req 1.6).
    await screen.findByText(/Hello, sign in/);
    expect(screen.queryByText(/Hello, Rahul/)).toBeNull();
  });
});

describe("AuthSessionContext — user switch replacement (Req 1.7)", () => {
  it("replaces the context user when logging out then in as a different user", async () => {
    const user = userEvent.setup();
    setupBackend(RAHUL);

    render(
      <AuthSessionProvider>
        <SessionProbe />
      </AuthSessionProvider>,
    );

    const probe = screen.getByTestId("current-user");

    // Hydrated as Rahul.
    await waitFor(() => expect(probe).toHaveTextContent("Rahul Verma"));

    // Log out clears the active user.
    await user.click(screen.getByRole("button", { name: "probe-logout" }));
    await waitFor(() => expect(probe).toHaveTextContent("none"));

    // Logging in as Priya replaces the context user with the new session.
    await user.click(screen.getByRole("button", { name: "probe-login-priya" }));
    await waitFor(() => expect(probe).toHaveTextContent("Priya Sharma"));
  });
});
