"use client";

/**
 * Seller orders page (Requirements 1.5, 11.1).
 *
 * When a user is signed in, this page fetches their order history from
 * `GET /api/returns/orders` and renders each purchase as an Amazon-style order
 * card. Every order shows a "Return Item" action; the "Resell via Amazon"
 * action is shown only when the order is `resell_eligible` (purchased more than
 * 7 days ago — Requirement 11.1). When signed out, it prompts the user to sign
 * in.
 *
 * The data fetch is keyed off `user?.user_id` so it re-fetches (and prior
 * orders are cleared) whenever the active user switches (Requirement 1.7).
 *
 * Clicking "Return Item" opens the AI verification scan modal
 * ({@link AIVerificationScanModal}) for that order; on scan completion the page
 * submits `POST /api/returns/initiate` and shows a confirmation banner on
 * success or an error banner on failure (Requirement 3.6).
 *
 * Clicking "Resell via Amazon" opens the mock AI condition grading modal
 * ({@link MockAIGradingScanModal}) for that order; on scan completion the page
 * submits `POST /api/resale/list` with the mock grade, mock condition image,
 * and suggested price (<= the product price) and shows a confirmation banner on
 * success or an error banner on failure (Requirement 11.5).
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2 } from "lucide-react";

import { AIVerificationScanModal } from "@/components/AIVerificationScanModal";
import {
  MockAIGradingScanModal,
  type GradingResult,
} from "@/components/MockAIGradingScanModal";
import { PrimaryButton } from "@/components/PrimaryButton";
import { ProductImage } from "@/components/ProductImage";
import { useAuthSession } from "@/context/AuthSessionContext";
import { ApiError, api } from "@/lib/api";
import { productImageSrc } from "@/lib/catalog";
import {
  LOCAL_ORDER_EVENT,
  getPlacedOrders,
  type PlacedOrder,
} from "@/lib/localOrders";

/** A single order returned by `GET /api/returns/orders`. */
export interface SellerOrder {
  order_history_id: number;
  asin: string;
  name: string;
  price: number;
  /** Official catalog image URL (NOT NULL on the backend). */
  image_url: string;
  /** Local path of an uploaded photo, or null until one is uploaded. */
  uploaded_image_path: string | null;
  /** ISO-8601 purchase timestamp. */
  purchased_at: string;
  days_since_purchase: number;
  /** True when purchased more than 7 days ago (Req 11.1). */
  resell_eligible: boolean;
  /** True when purchased within the last 7 days — return window is open. */
  return_eligible: boolean;
  /** Persisted ReturnOrder status when this purchase already has a return. */
  return_status?: string | null;
  /** ID of an existing resale listing for this order (null if none). */
  resale_listing_id?: number | null;
  /** Status of the existing resale listing: "ACTIVE", "SOLD", "REMOVED", or null. */
  resale_status?: string | null;
}

interface SellerOrdersResponse {
  orders: SellerOrder[];
}

/** Minimal shape of the created ReturnOrder from `POST /api/returns/initiate`. */
interface InitiateReturnResponse {
  return_order: {
    id: number;
    asin: string;
    status: string;
    initiated_at: string;
    expires_at: string;
  };
}

/** Minimal shape of the created ResaleListing from `POST /api/resale/list`. */
interface CreateListingResponse {
  resale_listing: {
    id: number;
    asin: string;
    status: string;
    condition_grade: string;
    resale_price: number;
    condition_image_url: string;
    listed_at: string;
  };
}

/** A transient confirmation/error banner shown after a return submission. */
interface OrdersBanner {
  kind: "success" | "error";
  message: string;
}

const currency = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 2,
});

function formatPurchaseDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString("en-IN", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

/**
 * A single Amazon-style order card.
 *
 * `onReturn` is always available; `onResell` is provided only when the order is
 * resell-eligible and not already listed. `onRemoveListing` is provided when
 * the order has an ACTIVE resale listing.
 */
function OrderCard({
  order,
  returned,
  onReturn,
  onResell,
  onRemoveListing,
  removingListingId,
}: {
  order: SellerOrder;
  returned: boolean;
  onReturn: (order: SellerOrder) => void;
  onResell: (order: SellerOrder) => void;
  onRemoveListing: (order: SellerOrder) => void;
  removingListingId: number | null;
}) {
  const returnCopy =
    order.return_status === "SCANNING"
      ? "Returned · scanning for nearby buyers"
      : order.return_status
        ? `Returned · ${order.return_status.replaceAll("_", " ").toLowerCase()}`
        : "Scanning for nearby buyers";

  const isActiveListing = order.resale_listing_id != null && order.resale_status === "ACTIVE";
  const isSoldListing = order.resale_status === "SOLD";
  const isRemovingThis = removingListingId === order.resale_listing_id;

  return (
    <li className="rounded-amazon border border-gray-300 bg-white shadow-sm">
      <div className="border-b border-gray-200 bg-amazonBg px-4 py-2 text-xs text-amazonInk">
        <span className="mr-4">
          <span className="block font-bold uppercase tracking-wide text-gray-600">
            Order placed
          </span>
          {formatPurchaseDate(order.purchased_at)}
        </span>
      </div>

      <div className="flex flex-col gap-4 p-4 sm:flex-row">
        <div className="shrink-0">
          <ProductImage
            src={order.uploaded_image_path || order.image_url}
            alt={order.name}
            className="aspect-square w-28"
          />
        </div>

        <div className="min-w-0 flex-1">
          <h2 className="truncate text-base font-bold text-amazonInk">
            {order.name}
          </h2>
          <p className="mt-1 text-xs text-gray-600">ASIN: {order.asin}</p>
          <p className="mt-1 text-sm font-bold text-amazonInk">
            {currency.format(order.price)}
          </p>
          <p className="mt-1 text-xs text-gray-600">
            Purchased {order.days_since_purchase}{" "}
            {order.days_since_purchase === 1 ? "day" : "days"} ago
          </p>
        </div>

        <div className="flex w-full shrink-0 flex-col gap-2 sm:w-48">
          {returned ? (
            <p className="inline-flex w-full items-center justify-center rounded-amazon border border-green-700 bg-green-50 px-4 py-2 text-center text-sm font-medium text-green-800">
              {returnCopy}
            </p>
          ) : order.return_eligible ? (
            <PrimaryButton onClick={() => onReturn(order)}>
              Return Item
            </PrimaryButton>
          ) : (
            <p className="inline-flex w-full items-center justify-center rounded-amazon border border-gray-300 bg-amazonBg px-3 py-2 text-center text-xs text-gray-600">
              Return window closed (over 7 days)
            </p>
          )}

          {order.resell_eligible ? (
            isActiveListing ? (
              /* Already listed — show badge + remove button */
              <>
                <p className="inline-flex w-full items-center justify-center gap-1 rounded-amazon border border-green-600 bg-green-50 px-3 py-2 text-center text-xs font-bold text-green-800">
                  ✅ Listed on Marketplace
                </p>
                <button
                  type="button"
                  disabled={isRemovingThis}
                  onClick={() => onRemoveListing(order)}
                  className="inline-flex w-full items-center justify-center rounded-amazon border border-red-400 bg-white px-4 py-2 text-sm font-medium text-red-600 shadow-sm hover:bg-red-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-400 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isRemovingThis ? "Removing…" : "Remove Listing"}
                </button>
              </>
            ) : isSoldListing ? (
              <p className="inline-flex w-full items-center justify-center rounded-amazon border border-gray-300 bg-amazonBg px-3 py-2 text-center text-xs text-gray-600">
                Sold on Marketplace
              </p>
            ) : (
              <button
                type="button"
                onClick={() => onResell(order)}
                className="inline-flex w-full items-center justify-center rounded-amazon border border-gray-400 bg-white px-4 py-2 text-sm font-medium text-amazonInk shadow-sm hover:bg-amazonBg focus:outline-none focus-visible:ring-2 focus-visible:ring-amazonOrange"
              >
                Resell via Amazon
              </button>
            )
          ) : null}
        </div>
      </div>
    </li>
  );
}

function PlacedOrderCard({ order }: { order: PlacedOrder }) {
  return (
    <li className="rounded-amazon border border-green-700 bg-white shadow-sm">
      <div className="flex flex-col gap-2 border-b border-green-100 bg-green-50 px-4 py-3 text-sm text-green-900 sm:flex-row sm:items-center sm:justify-between">
        <span className="inline-flex items-center gap-2 font-bold">
          <CheckCircle2 className="h-5 w-5" />
          Order placed
        </span>
        <span className="text-xs font-medium">
          {order.id} · {currency.format(order.total)}
        </span>
      </div>
      <ul className="divide-y divide-gray-100">
        {order.items.map((item) => (
          <li key={`${order.id}-${item.id}`} className="flex gap-4 p-4">
            <ProductImage
              src={productImageSrc(item)}
              alt={item.name}
              className="aspect-square w-20 shrink-0"
            />
            <div className="min-w-0 flex-1">
              <h3 className="line-clamp-2 text-sm font-bold text-amazonInk">
                {item.name}
              </h3>
              <p className="mt-1 text-xs text-gray-600">ASIN: {item.asin}</p>
              <p className="mt-2 text-sm font-bold text-amazonInk">
                {currency.format(item.price)}
              </p>
              <p className="mt-1 inline-flex rounded border border-amazonOrange bg-orange-50 px-2 py-0.5 text-xs font-bold text-amazonInk">
                {item.is_claimed_deal ? "Coming in 3 hours" : "Coming in 3 days"}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </li>
  );
}

export default function OrdersPage() {
  const { user, loading: sessionLoading } = useAuthSession();

  const [orders, setOrders] = useState<SellerOrder[]>([]);
  const [placedOrders, setPlacedOrders] = useState<PlacedOrder[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The order currently undergoing the AI verification scan, or null when the
  // scan modal is closed. The actual `POST /api/returns/initiate` is submitted
  // only after the scan completes (Requirement 3.6).
  const [scanningOrder, setScanningOrder] = useState<SellerOrder | null>(null);
  // The order currently undergoing the mock AI condition grading scan, or null
  // when the grading modal is closed. The `POST /api/resale/list` request is
  // submitted only after the grading scan completes (Requirement 11.5).
  const [gradingOrder, setGradingOrder] = useState<SellerOrder | null>(null);
  // Set of order_history_ids that have an active SCANNING return, so we can
  // reflect the new state on the card after a successful initiation.
  const [returnedOrderIds, setReturnedOrderIds] = useState<Set<number>>(
    () => new Set(),
  );
  // listing_id currently being removed (for per-card loading state).
  const [removingListingId, setRemovingListingId] = useState<number | null>(null);
  // Transient confirmation/error banner shown after a submission.
  const [banner, setBanner] = useState<OrdersBanner | null>(null);

  // Clicking "Return Item" opens the AI verification scan modal for the order.
  // Nothing is submitted yet — submission happens on scan completion.
  const handleReturn = useCallback((order: SellerOrder) => {
    setBanner(null);
    setScanningOrder(order);
  }, []);

  // Clicking "Resell via Amazon" opens the mock AI condition grading scan for
  // the order. Nothing is submitted yet — submission happens on scan
  // completion (Requirement 11.5).
  const handleResell = useCallback((order: SellerOrder) => {
    setBanner(null);
    setGradingOrder(order);
  }, []);

  // Clicking "Remove Listing" calls DELETE /api/resale/{id} and updates the
  // local orders list so the card switches back to "Resell via Amazon".
  const handleRemoveListing = useCallback(async (order: SellerOrder) => {
    if (!order.resale_listing_id) return;
    setBanner(null);
    setRemovingListingId(order.resale_listing_id);
    try {
      await api.del(`/api/resale/${order.resale_listing_id}`);
      // Update the order in local state so the card reflects the removal.
      setOrders((prev) =>
        prev.map((o) =>
          o.order_history_id === order.order_history_id
            ? { ...o, resale_listing_id: null, resale_status: "REMOVED" }
            : o,
        ),
      );
      setBanner({
        kind: "success",
        message: `${order.name} has been removed from the marketplace.`,
      });
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : "We couldn't remove your listing. Please try again.";
      setBanner({ kind: "error", message });
    } finally {
      setRemovingListingId(null);
    }
  }, []);

  // Invoked when the mock AI grading scan finishes (Requirement 11.5): only now
  // do we submit the resale listing with the mock grade, mock condition image,
  // and suggested price (clamped <= the product price), then close the modal
  // and show a confirmation (on success) or an error message (on failure).
  const handleGradingComplete = useCallback(
    async (result: GradingResult) => {
      const order = gradingOrder;
      if (!order) return;
      // Guard the price bound client-side too (Requirement 11.2): never submit
      // a resale price above the catalog price.
      const resalePrice = Math.min(result.suggested_price, order.price);
      try {
        const resp = await api.post<CreateListingResponse>("/api/resale/list", {
          order_history_id: order.order_history_id,
          condition_grade: result.condition_grade,
          condition_image_url: result.condition_image_url,
          resale_price: resalePrice,
        });
        // Update the order in local state so the card shows "Listed on Marketplace".
        setOrders((prev) =>
          prev.map((o) =>
            o.order_history_id === order.order_history_id
              ? {
                  ...o,
                  resale_listing_id: resp.resale_listing.id,
                  resale_status: "ACTIVE",
                }
              : o,
          ),
        );
        setBanner({
          kind: "success",
          message: `Listed on Amazon Local Verified Used Deals — ${order.name} (${result.condition_grade}).`,
        });
      } catch (err) {
        const message =
          err instanceof ApiError
            ? err.message
            : "We couldn't create your resale listing. Please try again.";
        setBanner({ kind: "error", message });
      } finally {
        setGradingOrder(null);
      }
    },
    [gradingOrder],
  );

  // Invoked when the AI verification scan finishes (Requirement 3.6): only now
  // do we submit the return initiation request, then close the modal and show a
  // confirmation (on success) or an error message (on failure).
  const handleScanComplete = useCallback(async () => {
    const order = scanningOrder;
    if (!order) return;
    try {
      await api.post<InitiateReturnResponse>("/api/returns/initiate", {
        order_history_id: order.order_history_id,
      });
      setReturnedOrderIds((prev) => {
        const next = new Set(prev);
        next.add(order.order_history_id);
        return next;
      });
      setBanner({
        kind: "success",
        message: `Return is now scanning for nearby buyers — ${order.name}.`,
      });
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : "We couldn't start your return. Please try again.";
      setBanner({ kind: "error", message });
    } finally {
      setScanningOrder(null);
    }
  }, [scanningOrder]);

  useEffect(() => {
    // Key the fetch off the active user id so a user switch re-fetches and
    // clears the previous user's orders (Req 1.7).
    if (!user) {
      setOrders([]);
      setPlacedOrders([]);
      setError(null);
      setLoading(false);
      setReturnedOrderIds(new Set());
      setScanningOrder(null);
      setGradingOrder(null);
      setBanner(null);
      return;
    }

    let active = true;
    setLoading(true);
    setError(null);
    // Clear stale data immediately on user switch.
    setOrders([]);
    setPlacedOrders(getPlacedOrders(user.user_id));
    setReturnedOrderIds(new Set());
    setScanningOrder(null);
    setGradingOrder(null);
    setBanner(null);

    (async () => {
      try {
        const data = await api.get<SellerOrdersResponse>("/api/returns/orders");
        if (active) setOrders(data.orders ?? []);
      } catch {
        if (active) {
          setError("We couldn't load your orders. Please try again.");
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
    if (!user) return;
    const refreshPlacedOrders = () => {
      setPlacedOrders(getPlacedOrders(user.user_id));
    };
    refreshPlacedOrders();
    window.addEventListener(LOCAL_ORDER_EVENT, refreshPlacedOrders);
    window.addEventListener("storage", refreshPlacedOrders);
    return () => {
      window.removeEventListener(LOCAL_ORDER_EVENT, refreshPlacedOrders);
      window.removeEventListener("storage", refreshPlacedOrders);
    };
  }, [user?.user_id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Signed-out state — prompt to sign in (Req 1.5 gates seller actions on auth).
  if (!user && !sessionLoading) {
    return (
      <section className="mx-auto max-w-md">
        <div className="rounded-amazon border border-gray-300 bg-white p-6 text-center shadow-sm">
          <h1 className="text-2xl font-bold text-amazonInk">Your Orders</h1>
          <p className="mt-2 text-sm text-amazonInk">
            Sign in to view your orders and start a return or resale listing.
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

  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-bold text-amazonInk">Your Orders</h1>

      {banner ? (
        <div
          role={banner.kind === "error" ? "alert" : "status"}
          className={
            banner.kind === "success"
              ? "rounded border border-green-700 bg-green-50 p-3 text-sm text-green-800"
              : "rounded border border-red-600 bg-red-50 p-3 text-sm text-red-700"
          }
        >
          {banner.message}
        </div>
      ) : null}

      {loading || sessionLoading ? (
        <p className="text-sm text-amazonInk">Loading your orders…</p>
      ) : error ? (
        <div
          role="alert"
          className="rounded border border-red-600 bg-red-50 p-3 text-sm text-red-700"
        >
          {error}
        </div>
      ) : orders.length === 0 && placedOrders.length === 0 ? (
        <div className="rounded-amazon border border-gray-300 bg-white p-6 text-sm text-amazonInk shadow-sm">
          You don&apos;t have any orders yet.
        </div>
      ) : (
        <div className="space-y-6">
          {placedOrders.length > 0 ? (
            <section className="space-y-3">
              <h2 className="text-lg font-bold text-amazonInk">Profile orders</h2>
              <ul className="space-y-4">
                {placedOrders.map((order) => (
                  <PlacedOrderCard key={order.id} order={order} />
                ))}
              </ul>
            </section>
          ) : null}

          {orders.length > 0 ? (
            <section className="space-y-3">
              <h2 className="text-lg font-bold text-amazonInk">
                Returns and seller orders
              </h2>
              <ul className="space-y-4">
                {orders.map((order) => (
                  <OrderCard
                    key={order.order_history_id}
                    order={order}
                    returned={
                      Boolean(order.return_status) ||
                      returnedOrderIds.has(order.order_history_id)
                    }
                    onReturn={handleReturn}
                    onResell={handleResell}
                    onRemoveListing={handleRemoveListing}
                    removingListingId={removingListingId}
                  />
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      )}

      <AIVerificationScanModal
        open={scanningOrder !== null}
        productName={scanningOrder?.name}
        imageUrl={
          scanningOrder?.uploaded_image_path || scanningOrder?.image_url
        }
        onComplete={handleScanComplete}
      />

      <MockAIGradingScanModal
        open={gradingOrder !== null}
        productName={gradingOrder?.name}
        imageUrl={gradingOrder?.uploaded_image_path || gradingOrder?.image_url}
        productKey={gradingOrder?.asin}
        productPrice={gradingOrder?.price}
        onComplete={handleGradingComplete}
      />
    </section>
  );
}
