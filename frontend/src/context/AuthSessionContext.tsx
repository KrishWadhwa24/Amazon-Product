"use client";

/**
 * Global authentication/session context (Requirement 1).
 *
 * On mount the provider hydrates the active user from `GET /api/auth/session`
 * (Req 1.4). It exposes `login`, `logout`, and `refresh` actions that update the
 * context so user-specific content reflects the newly authenticated session
 * (Req 1.6, 1.7). Consumers read `user` (and `user.user_id`) so that user-scoped
 * surfaces (cart, orders, notifications) can key off the active user and
 * re-fetch/clear when the user changes within the 3-second bound (Req 1.7).
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { ApiError, api } from "@/lib/api";

/** The authenticated user shape returned by the auth endpoints. */
export interface AuthUser {
  user_id: number;
  name: string;
  role: string;
  /** True when the user has >= 1 OrderHistory record and may act as Seller (Req 1.5). */
  can_sell: boolean;
}

/** Public API exposed by {@link AuthSessionContext}. */
export interface AuthSessionContextValue {
  /** The active authenticated user, or null when signed out. */
  user: AuthUser | null;
  /** True while the initial session hydration request is in flight. */
  loading: boolean;
  /**
   * Authenticate with the given credentials. Resolves on success and updates
   * `user`; rejects with an {@link ApiError} (`AUTH_FAILED`) on failure so the
   * caller can show an authentication-failed message (Req 1.1, 1.3).
   */
  login: (email: string, password: string) => Promise<AuthUser>;
  /** Terminate the active session and clear `user` (Req 1.6). */
  logout: () => Promise<void>;
  /** Re-hydrate `user` from the backend session (Req 1.4, 1.7). */
  refresh: () => Promise<void>;
}

const AuthSessionContext = createContext<AuthSessionContextValue | null>(null);

/**
 * Read the current session from `GET /api/auth/session`.
 *
 * Returns null on a 401 (no active session) and rethrows other errors so
 * transient failures are not silently treated as "signed out".
 */
async function fetchSession(): Promise<AuthUser | null> {
  try {
    return await api.get<AuthUser>("/api/auth/session");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return null;
    }
    throw error;
  }
}

export function AuthSessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  const refresh = useCallback(async () => {
    try {
      const session = await fetchSession();
      setUser(session);
    } catch {
      // Treat an unexpected session-read failure as signed out for the UI;
      // the next action (login/refresh) can recover the real state.
      setUser(null);
    }
  }, []);

  // Hydrate the session once on mount (Req 1.4).
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const session = await fetchSession();
        if (active) setUser(session);
      } catch {
        if (active) setUser(null);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const login = useCallback(
    async (email: string, password: string): Promise<AuthUser> => {
      // Throws ApiError (401 AUTH_FAILED) on bad credentials (Req 1.3).
      const authed = await api.post<AuthUser>("/api/auth/login", {
        email,
        password,
      });
      // Replace the active user so user-specific content reflects the new
      // session immediately (Req 1.6, 1.7).
      setUser(authed);
      return authed;
    },
    [],
  );

  const logout = useCallback(async () => {
    try {
      await api.post("/api/auth/logout");
    } finally {
      // Clear local session state regardless of the network result so no
      // subsequent render is associated with the prior user (Req 1.6).
      setUser(null);
    }
  }, []);

  const value = useMemo<AuthSessionContextValue>(
    () => ({ user, loading, login, logout, refresh }),
    [user, loading, login, logout, refresh],
  );

  return (
    <AuthSessionContext.Provider value={value}>
      {children}
    </AuthSessionContext.Provider>
  );
}

/**
 * Access the auth/session context. Must be used within an
 * {@link AuthSessionProvider}.
 */
export function useAuthSession(): AuthSessionContextValue {
  const ctx = useContext(AuthSessionContext);
  if (ctx === null) {
    throw new Error("useAuthSession must be used within an AuthSessionProvider");
  }
  return ctx;
}
