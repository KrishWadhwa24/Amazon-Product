"use client";

/**
 * Product detail BuyBox (Requirements 4.1, 4.2, 4.3).
 *
 * Renders the price and the buyer purchase-intent actions for a product:
 *  - "Add to Cart"   → `POST /api/cart`     (records a cart demand signal — Req 4.1)
 *  - "Buy Now"       → `POST /api/buynow`   (records a buy-now signal — Req 4.2)
 *  - "Add to Wish List" → `POST /api/wishlist` (records a wishlist signal — Req 4.3)
 *
 * These actions require an authenticated buyer session. When signed out, the
 * BuyBox shows a sign-in prompt instead of the action buttons. After a
 * successful "Add to Cart" a small inline confirmation is shown. The cart-add
 * call is what triggers backend matching; the nearby-return match popup itself
 * is delivered by the global notification poller (task 21.2), not here.
 */

import { useCallback, useState } from "react";
import Link from "next/link";

import { PrimaryButton } from "@/components/PrimaryButton";
import { useAuthSession } from "@/context/AuthSessionContext";
import { ApiError, api } from "@/lib/api";
import { inr, type Product } from "@/lib/catalog";

type Banner = { kind: "success" | "error"; message: string };

/** Which action is currently in flight, used to disable buttons. */
type PendingAction = "cart" | "buynow" | "wishlist" | null;

export function BuyBox({ product }: { product: Product }) {
  const { user } = useAuthSession();
  const [pending, setPending] = useState<PendingAction>(null);
  const [banner, setBanner] = useState<Banner | null>(null);

  const runAction = useCallback(
    async (
      action: Exclude<PendingAction, null>,
      path: string,
      successMessage: string,
    ) => {
      setBanner(null);
      setPending(action);
      try {
        await api.post(path, { asin: product.asin });
        setBanner({ kind: "success", message: successMessage });
      } catch (err) {
        const message =
          err instanceof ApiError
            ? err.message
            : "Something went wrong. Please try again.";
        setBanner({ kind: "error", message });
      } finally {
        setPending(null);
      }
    },
    [product.asin],
  );

  return (
    <div className="rounded-amazon border border-gray-300 bg-white p-4 shadow-sm">
      <p className="text-2xl font-bold text-amazonInk">
        {inr.format(product.price)}
      </p>

      {user ? (
        <div className="mt-4 space-y-2">
          <PrimaryButton
            disabled={pending !== null}
            onClick={() =>
              void runAction(
                "cart",
                "/api/cart",
                `Added to Cart — ${product.name}.`,
              )
            }
          >
            {pending === "cart" ? "Adding…" : "Add to Cart"}
          </PrimaryButton>

          <button
            type="button"
            disabled={pending !== null}
            onClick={() =>
              void runAction(
                "buynow",
                "/api/buynow",
                "Buy Now started — we'll look for a faster local deal.",
              )
            }
            className="inline-flex w-full items-center justify-center rounded-amazon border border-[#a88734]/60 bg-amazonOrange px-4 py-2 text-sm font-medium text-amazonInk shadow-sm hover:brightness-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-amazonOrange disabled:cursor-not-allowed disabled:opacity-60"
          >
            {pending === "buynow" ? "Processing…" : "Buy Now"}
          </button>

          <button
            type="button"
            disabled={pending !== null}
            onClick={() =>
              void runAction(
                "wishlist",
                "/api/wishlist",
                "Added to your Wish List.",
              )
            }
            className="inline-flex w-full items-center justify-center rounded-amazon border border-gray-400 bg-white px-4 py-2 text-sm font-medium text-amazonInk shadow-sm hover:bg-amazonBg focus:outline-none focus-visible:ring-2 focus-visible:ring-amazonOrange disabled:cursor-not-allowed disabled:opacity-60"
          >
            {pending === "wishlist" ? "Adding…" : "Add to Wish List"}
          </button>

          {banner ? (
            <p
              role={banner.kind === "error" ? "alert" : "status"}
              className={
                banner.kind === "success"
                  ? "rounded border border-green-700 bg-green-50 p-2 text-xs text-green-800"
                  : "rounded border border-red-600 bg-red-50 p-2 text-xs text-red-700"
              }
            >
              {banner.message}
            </p>
          ) : null}
        </div>
      ) : (
        <div className="mt-4 rounded border border-gray-300 bg-amazonBg p-3 text-sm text-amazonInk">
          <p className="font-medium">Sign in to buy this item.</p>
          <p className="mt-1 text-xs text-gray-600">
            Add to cart, buy now, and wish list require an account.
          </p>
          <div className="mt-3">
            <Link href="/login">
              <PrimaryButton>Sign in</PrimaryButton>
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
