"use client";

import Link from "next/link";
import { MapPin, Search, ShoppingCart, Sparkles, Store, User } from "lucide-react";

import { useAuthSession } from "@/context/AuthSessionContext";

const SECONDARY_LINKS: { label: string; href?: string }[] = [
  { label: "Today's Deals" },
  { label: "Local Deals", href: "/local-deals" },
  { label: "Resale Marketplace", href: "/local-marketplace" },
  { label: "Returns & Orders", href: "/orders" },
  { label: "Operations" },
];

/**
 * Amazon-style navigation shell (Req 17.1).
 *
 * Top bar uses the navy token (#232F3E) and contains the logo text, a delivery
 * location, a search bar, an account/user area, and a cart icon. Below it sits
 * the secondary dark band (#131921) with quick links. The account area reflects
 * the active session (Req 1.6, 1.7): it greets the logged-in user by name and
 * exposes a sign-out action, or links to `/login` when signed out.
 */
export function NavBar() {
  const { user, loading, logout } = useAuthSession();
  const firstName = user ? user.name.split(" ")[0] : null;

  return (
    <header className="w-full">
      {/* Top bar — navy */}
      <div className="bg-amazonNavy text-white">
        <div className="mx-auto flex w-full max-w-7xl items-center gap-3 px-4 py-2">
          {/* Logo */}
          <div className="flex shrink-0 items-center gap-3">
            <Link
              href="/"
              className="rounded px-1 text-2xl font-black tracking-normal hover:outline hover:outline-1 hover:outline-white"
            >
              <span>amazon</span>
              <span className="text-amazonOrange">.edge</span>
            </Link>
            <Link
              href="/local-marketplace"
              className="hidden items-center gap-2 rounded-amazon border border-amazonOrange/60 bg-white/10 px-3 py-1.5 text-sm font-bold text-white shadow-sm hover:bg-white/15 lg:flex"
            >
              <Store className="h-4 w-4 text-amazonOrange" aria-hidden="true" />
              Local Marketplace
            </Link>
          </div>

          {/* Deliver to / location */}
          <button
            type="button"
            className="hidden items-center gap-1 rounded px-1 text-left hover:outline hover:outline-1 hover:outline-white sm:flex"
          >
            <MapPin className="h-4 w-4 text-white" aria-hidden="true" />
            <span className="leading-tight">
              <span className="block text-xs text-gray-300">Deliver to</span>
              <span className="block text-sm font-bold">Bengaluru</span>
            </span>
          </button>

          {/* Search bar */}
          <form
            role="search"
            className="flex min-w-0 flex-1 items-stretch overflow-hidden rounded-amazon"
            action="/"
          >
            <input
              type="search"
              aria-label="Search Amazon Edge-Return"
              placeholder="Search products"
              className="min-w-0 flex-1 px-3 py-2 text-sm text-amazonInk focus:outline-none"
            />
            <button
              type="submit"
              aria-label="Search"
              className="flex items-center justify-center bg-amazonOrange px-3 text-amazonInk hover:brightness-95"
            >
              <Search className="h-5 w-5" aria-hidden="true" />
            </button>
          </form>

          {/* Account / user area */}
          {user ? (
            <div className="hidden items-center gap-2 sm:flex">
              <Link
                href="/orders"
                className="flex items-center gap-1 rounded px-1 hover:outline hover:outline-1 hover:outline-white"
              >
                <User className="h-4 w-4" aria-hidden="true" />
                <span className="leading-tight">
                  <span className="block text-xs text-gray-300">
                    Hello, {firstName}
                  </span>
                  <span className="block text-sm font-bold">
                    Account &amp; Lists
                  </span>
                </span>
              </Link>
              <button
                type="button"
                onClick={() => {
                  void logout();
                }}
                className="rounded px-1 text-xs font-bold text-gray-200 hover:text-white hover:outline hover:outline-1 hover:outline-white"
              >
                Sign out
              </button>
            </div>
          ) : (
            <Link
              href="/login"
              className="hidden items-center gap-1 rounded px-1 hover:outline hover:outline-1 hover:outline-white sm:flex"
            >
              <User className="h-4 w-4" aria-hidden="true" />
              <span className="leading-tight">
                <span className="block text-xs text-gray-300">
                  {loading ? "Loading…" : "Hello, sign in"}
                </span>
                <span className="block text-sm font-bold">
                  Account &amp; Lists
                </span>
              </span>
            </Link>
          )}

          {/* Cart */}
          <Link
            href="/cart"
            className="flex items-center gap-1 rounded px-1 hover:outline hover:outline-1 hover:outline-white"
            aria-label="Cart"
          >
            <ShoppingCart className="h-6 w-6" aria-hidden="true" />
            <span className="hidden text-sm font-bold sm:inline">Cart</span>
          </Link>
        </div>
      </div>

      {/* Secondary band — dark */}
      <nav className="border-t border-white/10 bg-amazonDark text-white">
        <ul className="mx-auto flex w-full max-w-7xl items-center gap-3 overflow-x-auto px-4 py-2 text-sm">
          <li className="whitespace-nowrap">
            <Link
              href="/local-marketplace"
              className="inline-flex items-center gap-2 rounded-amazon bg-amazonOrange px-3 py-1.5 text-sm font-extrabold text-amazonInk shadow-sm hover:brightness-95"
            >
              <Sparkles className="h-4 w-4" aria-hidden="true" />
              Local Marketplace
            </Link>
          </li>
          {SECONDARY_LINKS.map(({ label, href }) => (
            <li key={label} className="whitespace-nowrap">
              {href ? (
                <Link
                  href={href}
                  className="cursor-pointer rounded px-2 py-1 font-medium hover:outline hover:outline-1 hover:outline-white"
                >
                  {label}
                </Link>
              ) : (
                <span className="cursor-pointer rounded px-2 py-1 font-medium hover:outline hover:outline-1 hover:outline-white">
                  {label}
                </span>
              )}
            </li>
          ))}
        </ul>
      </nav>
    </header>
  );
}
