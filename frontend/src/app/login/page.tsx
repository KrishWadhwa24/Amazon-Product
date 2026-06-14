"use client";

/**
 * Login page (Requirement 1.1, 1.3).
 *
 * Lists the seeded demo accounts with one-click prefill (this is a demo) and an
 * email/password form. On submit it calls `login()` from the AuthSessionContext;
 * on success it redirects to the home page (/), and on failure (401 AUTH_FAILED)
 * it shows an authentication-failed message.
 */

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import { PrimaryButton } from "@/components/PrimaryButton";
import { ApiError } from "@/lib/api";
import { useAuthSession } from "@/context/AuthSessionContext";

/** Seeded demo accounts (from seed.py). Passwords are demo-only. */
interface DemoAccount {
  name: string;
  email: string;
  password: string;
  role: string;
}

const DEMO_ACCOUNTS: readonly DemoAccount[] = [
  {
    name: "Priya Sharma",
    email: "priya.sharma@example.com",
    password: "priya",
    role: "Seller",
  },
  {
    name: "Rahul Verma",
    email: "rahul.verma@example.com",
    password: "rahul",
    role: "Buyer",
  },
];

const AUTH_FAILED_MESSAGE =
  "Authentication failed. The email or password you entered is incorrect.";

export default function LoginPage() {
  const router = useRouter();
  const { login } = useAuthSession();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function prefill(account: DemoAccount) {
    setEmail(account.email);
    setPassword(account.password);
    setError(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      // On success, redirect to home so user-specific content reflects the
      // newly authenticated session (Req 1.7).
      router.push("/");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(
          err.code === "AUTH_FAILED" ? AUTH_FAILED_MESSAGE : err.message,
        );
      } else {
        setError("Something went wrong while signing in. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="mx-auto max-w-md space-y-6">
      <div className="rounded-amazon border border-gray-300 bg-white p-6 shadow-sm">
        <h1 className="text-2xl font-bold text-amazonInk">Sign in</h1>

        {error ? (
          <div
            role="alert"
            className="mt-4 rounded border border-red-600 bg-red-50 p-3 text-sm text-red-700"
          >
            {error}
          </div>
        ) : null}

        <form className="mt-4 space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-1">
            <label
              htmlFor="email"
              className="block text-sm font-bold text-amazonInk"
            >
              Email
            </label>
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded border border-gray-400 px-3 py-2 text-sm text-amazonInk focus:border-amazonOrange focus:outline-none focus-visible:ring-2 focus-visible:ring-amazonOrange"
            />
          </div>

          <div className="space-y-1">
            <label
              htmlFor="password"
              className="block text-sm font-bold text-amazonInk"
            >
              Password
            </label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded border border-gray-400 px-3 py-2 text-sm text-amazonInk focus:border-amazonOrange focus:outline-none focus-visible:ring-2 focus-visible:ring-amazonOrange"
            />
          </div>

          <PrimaryButton type="submit" disabled={submitting}>
            {submitting ? "Signing in…" : "Sign in"}
          </PrimaryButton>
        </form>
      </div>

      <div className="rounded-amazon border border-gray-300 bg-white p-6 shadow-sm">
        <h2 className="text-sm font-bold text-amazonInk">Demo accounts</h2>
        <p className="mt-1 text-xs text-amazonInk">
          Select an account to prefill the form, then sign in.
        </p>
        <ul className="mt-3 space-y-2">
          {DEMO_ACCOUNTS.map((account) => (
            <li key={account.email}>
              <button
                type="button"
                onClick={() => prefill(account)}
                className="flex w-full items-center justify-between rounded border border-gray-300 px-3 py-2 text-left text-sm hover:border-amazonOrange hover:bg-amazonBg focus:outline-none focus-visible:ring-2 focus-visible:ring-amazonOrange"
              >
                <span className="leading-tight">
                  <span className="block font-bold text-amazonInk">
                    {account.name}
                  </span>
                  <span className="block text-xs text-amazonInk">
                    {account.email}
                  </span>
                </span>
                <span className="rounded-full bg-amazonDark px-2 py-0.5 text-xs font-bold text-white">
                  {account.role}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
