"use client";

/**
 * Cart page (Requirements 4.1 buyer surface).
 *
 * When signed in, this page fetches `GET /api/cart` and lists each cart line
 * item with its image ({@link ProductImage}), name, and price, plus a computed
 * subtotal. When the cart is empty it shows a friendly empty state. When signed
 * out it prompts the user to sign in.
 *
 * The fetch is keyed off `user?.user_id` so it re-fetches (and the previous
 * user's cart is cleared) whenever the active user switches (Req 1.7).
 */

import { useEffect, useState } from "react";
import Link from "next/link";

import { PrimaryButton } from "@/components/PrimaryButton";
import { ProductImage } from "@/components/ProductImage";
import { useAuthSession } from "@/context/AuthSessionContext";
import { api } from "@/lib/api";
import { inr, productImageSrc, cartLinePrice, type CartItem } from "@/lib/catalog";
import {
  CLAIMED_DEAL_DISCOUNT,
  LOCAL_ORDER_EVENT,
  countClaimedDealsInCart,
  getClaimedDealAsins,
} from "@/lib/localOrders";

export default function CartPage() {
  const { user, loading: sessionLoading } = useAuthSession();

  const [items, setItems] = useState<CartItem[]>([]);
  const [claimedDealAsins, setClaimedDealAsins] = useState<Set<string>>(
    () => new Set(),
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Key the fetch off the active user id so a user switch re-fetches and
    // clears the previous user's cart (Req 1.7).
    if (!user) {
      setItems([]);
      setError(null);
      setLoading(false);
      return;
    }

    let active = true;
    setLoading(true);
    setError(null);
    setItems([]);

    (async () => {
      try {
        const data = await api.get<CartItem[]>("/api/cart");
        if (active) setItems(data ?? []);
      } catch {
        if (active) {
          setError("We couldn't load your cart. Please try again.");
        }
      } finally {
        if (active) setLoading(false);
      }
    })();

    return () => {
      active = false;
    };
  }, [user?.user_id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!user) {
      setClaimedDealAsins(new Set());
      return;
    }

    const refreshDeals = () => {
      setClaimedDealAsins(getClaimedDealAsins(user.user_id));
    };
    refreshDeals();
    window.addEventListener(LOCAL_ORDER_EVENT, refreshDeals);
    window.addEventListener("storage", refreshDeals);
    return () => {
      window.removeEventListener(LOCAL_ORDER_EVENT, refreshDeals);
      window.removeEventListener("storage", refreshDeals);
    };
  }, [user?.user_id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Signed-out state — prompt to sign in.
  if (!user && !sessionLoading) {
    return (
      <section className="mx-auto max-w-md">
        <div className="rounded-amazon border border-gray-300 bg-white p-6 text-center shadow-sm">
          <h1 className="text-2xl font-bold text-amazonInk">Your Cart</h1>
          <p className="mt-2 text-sm text-amazonInk">
            Sign in to see the items in your cart.
          </p>
          <div className="mx-auto mt-4 max-w-xs">
            <Link href="/login">
              <PrimaryButton>Sign in</PrimaryButton>
            </Link>
          </div>
        </div>
      </section>
    );
  }

  const subtotal = items.reduce((sum, item) => sum + item.product.price, 0);
  const openBoxDiscount = items.reduce(
    (sum, item) => sum + Math.max(0, item.product.price - cartLinePrice(item)),
    0,
  );
  const claimedDealDiscount = user
    ? countClaimedDealsInCart(user.user_id, items) * CLAIMED_DEAL_DISCOUNT
    : 0;
  const totalDiscount = openBoxDiscount + claimedDealDiscount;
  const total = Math.max(0, subtotal - totalDiscount);
  const itemCount = items.length;

  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-bold text-amazonInk">Shopping Cart</h1>

      {loading || sessionLoading ? (
        <p className="text-sm text-amazonInk">Loading your cart…</p>
      ) : error ? (
        <div
          role="alert"
          className="rounded border border-red-600 bg-red-50 p-3 text-sm text-red-700"
        >
          {error}
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-amazon border border-gray-300 bg-white p-8 text-center shadow-sm">
          <p className="text-base font-bold text-amazonInk">
            Your Amazon Cart is empty
          </p>
          <p className="mx-auto mt-1 max-w-md text-sm text-gray-600">
            Browse the catalog and add items to your cart to see them here.
          </p>
          <div className="mx-auto mt-4 max-w-xs">
            <Link href="/">
              <PrimaryButton>Shop the catalog</PrimaryButton>
            </Link>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-12">
          {/* Cart line items */}
          <ul className="space-y-3 md:col-span-9">
            {items.map((item) => (
              <li
                key={item.id}
                className="flex gap-4 rounded-amazon border border-gray-200 bg-white p-4 shadow-sm"
              >
                <div className="shrink-0">
                  <ProductImage
                    src={productImageSrc(item.product)}
                    alt={item.product.name}
                    className="aspect-square w-24"
                  />
                </div>
                <div className="min-w-0 flex-1">
                  <Link
                    href={`/product/${encodeURIComponent(item.product.asin)}`}
                    className="line-clamp-2 text-base font-medium text-amazonLink hover:text-amazonOrange"
                  >
                    {item.product.name}
                  </Link>
                  <p className="mt-1 text-xs text-gray-600">
                    ASIN: {item.product.asin}
                  </p>
                  {item.resale_listing_id ? (
                    <p className="mt-1 inline-flex items-center gap-1 rounded border border-amber-600 bg-amber-50 px-2 py-0.5 text-xs font-bold text-amber-700">
                      Open-box deal
                      {item.condition_grade ? ` · ${item.condition_grade}` : ""}
                    </p>
                  ) : null}
                  {claimedDealAsins.has(item.product.asin) ? (
                    <p className="mt-2 inline-flex items-center gap-1 rounded border border-green-700 bg-green-50 px-2 py-0.5 text-xs font-bold text-green-800">
                      Claimed deal · ₹100 off · arrives in 3 hours
                    </p>
                  ) : null}
                  <p className="mt-2 text-lg font-bold text-amazonInk">
                    {inr.format(cartLinePrice(item))}
                  </p>
                </div>
              </li>
            ))}
          </ul>

          {/* Price summary */}
          <aside className="md:col-span-3">
            <div className="rounded-amazon border border-gray-300 bg-white p-4 shadow-sm">
              <h2 className="text-base font-bold text-amazonInk">
                Price details
              </h2>
              <dl className="mt-3 space-y-2 text-sm text-amazonInk">
                {items.map((item) => (
                  <div key={item.id} className="flex justify-between gap-3">
                    <dt className="min-w-0 truncate">{item.product.name}</dt>
                    <dd className="shrink-0 font-medium">
                      {inr.format(item.product.price)}
                    </dd>
                  </div>
                ))}
                <div className="border-t border-gray-200 pt-2">
                  <div className="flex justify-between">
                    <dt>
                      Items ({itemCount} {itemCount === 1 ? "item" : "items"})
                    </dt>
                    <dd className="font-medium">{inr.format(subtotal)}</dd>
                  </div>
                </div>
                <div className="flex justify-between text-green-800">
                  <dt>Discount</dt>
                  <dd className="font-bold">-{inr.format(totalDiscount)}</dd>
                </div>
                {claimedDealDiscount > 0 ? (
                  <div className="flex justify-between text-xs text-green-800">
                    <dt>Claim deal bonus</dt>
                    <dd>-{inr.format(claimedDealDiscount)}</dd>
                  </div>
                ) : null}
                <div className="flex justify-between border-t border-gray-200 pt-2 text-base font-bold">
                  <dt>Total</dt>
                  <dd>{inr.format(total)}</dd>
                </div>
              </dl>
              <div className="mt-3">
                <Link href="/checkout">
                  <PrimaryButton>Proceed to checkout</PrimaryButton>
                </Link>
              </div>
            </div>
          </aside>
        </div>
      )}
    </section>
  );
}
