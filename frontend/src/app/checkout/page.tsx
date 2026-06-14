"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { CheckCircle2, CreditCard, IndianRupee, MapPin } from "lucide-react";

import { PrimaryButton } from "@/components/PrimaryButton";
import { ProductImage } from "@/components/ProductImage";
import { useAuthSession } from "@/context/AuthSessionContext";
import { api } from "@/lib/api";
import { inr, productImageSrc, cartLinePrice, type CartItem } from "@/lib/catalog";
import {
  CLAIMED_DEAL_DISCOUNT,
  countClaimedDealsInCart,
  getClaimedDealAsins,
  savePlacedOrder,
  type PlacedOrder,
} from "@/lib/localOrders";

type PaymentMethod = "card" | "upi" | "cod";

export default function CheckoutPage() {
  const { user, loading: sessionLoading } = useAuthSession();
  const [items, setItems] = useState<CartItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [address, setAddress] = useState(
    "221B Indiranagar Main Road, Bengaluru, Karnataka 560038",
  );
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>("cod");
  const [placedOrder, setPlacedOrder] = useState<PlacedOrder | null>(null);

  useEffect(() => {
    if (!user) {
      setItems([]);
      return;
    }

    let active = true;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const data = await api.get<CartItem[]>("/api/cart");
        if (active) setItems(data ?? []);
      } catch {
        if (active) setError("We couldn't load your checkout. Please try again.");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [user?.user_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const totals = useMemo(() => {
    const subtotal = items.reduce((sum, item) => sum + item.product.price, 0);
    const openBoxDiscount = items.reduce(
      (sum, item) => sum + Math.max(0, item.product.price - cartLinePrice(item)),
      0,
    );
    const claimedDealDiscount = user
      ? countClaimedDealsInCart(user.user_id, items) * CLAIMED_DEAL_DISCOUNT
      : 0;
    const discount = openBoxDiscount + claimedDealDiscount;
    return {
      subtotal,
      discount,
      total: Math.max(0, subtotal - discount),
    };
  }, [items, user?.user_id]); // eslint-disable-line react-hooks/exhaustive-deps

  function placeOrder(method: PaymentMethod) {
    if (!user || items.length === 0) return;
    setPaymentMethod(method);
    const claimed = getClaimedDealAsins(user.user_id);
    const order: PlacedOrder = {
      id: `AE-${Date.now().toString(36).toUpperCase()}`,
      placed_at: new Date().toISOString(),
      address,
      payment_method: method === "cod" ? "Cash on Delivery" : "Demo payment",
      subtotal: totals.subtotal,
      discount: totals.discount,
      total: totals.total,
      items: items.map((item) => ({
        id: item.id,
        asin: item.product.asin,
        name: item.product.name,
        price: cartLinePrice(item),
        image_url: item.product.image_url,
        uploaded_image_path: item.product.uploaded_image_path,
        is_claimed_deal: claimed.has(item.product.asin),
      })),
    };
    savePlacedOrder(user.user_id, order);
    setPlacedOrder(order);
  }

  if (!user && !sessionLoading) {
    return (
      <section className="mx-auto max-w-md rounded-amazon border border-gray-300 bg-white p-6 text-center shadow-sm">
        <h1 className="text-2xl font-bold text-amazonInk">Checkout</h1>
        <p className="mt-2 text-sm text-gray-700">Sign in to place your order.</p>
        <div className="mx-auto mt-4 max-w-xs">
          <Link href="/login">
            <PrimaryButton>Sign in</PrimaryButton>
          </Link>
        </div>
      </section>
    );
  }

  if (placedOrder) {
    return (
      <section className="mx-auto max-w-2xl rounded-amazon border border-green-700 bg-white p-8 text-center shadow-sm">
        <CheckCircle2 className="mx-auto h-14 w-14 text-green-700" />
        <h1 className="mt-3 text-2xl font-bold text-green-800">Order placed</h1>
        <p className="mt-2 text-sm text-amazonInk">
          {placedOrder.id} · {placedOrder.payment_method}
        </p>
        <p className="mt-1 text-sm font-bold text-amazonInk">
          Total paid: {inr.format(placedOrder.total)}
        </p>
        <div className="mx-auto mt-5 max-w-xs">
          <Link href="/orders">
            <PrimaryButton>View in profile</PrimaryButton>
          </Link>
        </div>
      </section>
    );
  }

  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-bold text-amazonInk">Checkout</h1>

      {loading || sessionLoading ? (
        <p className="text-sm text-amazonInk">Preparing checkout…</p>
      ) : error ? (
        <div role="alert" className="rounded border border-red-600 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-amazon border border-gray-300 bg-white p-6 text-sm text-amazonInk shadow-sm">
          Your cart is empty.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          <div className="space-y-4 lg:col-span-8">
            <section className="rounded-amazon border border-gray-300 bg-white p-4 shadow-sm">
              <div className="flex items-center gap-2">
                <MapPin className="h-5 w-5 text-amazonOrange" />
                <h2 className="text-lg font-bold text-amazonInk">Delivery address</h2>
              </div>
              <textarea
                value={address}
                onChange={(event) => setAddress(event.target.value)}
                className="mt-3 min-h-24 w-full rounded-amazon border border-gray-300 p-3 text-sm text-amazonInk focus:border-amazonOrange focus:outline-none focus:ring-1 focus:ring-amazonOrange"
              />
            </section>

            <section className="rounded-amazon border border-gray-300 bg-white p-4 shadow-sm">
              <div className="flex items-center gap-2">
                <CreditCard className="h-5 w-5 text-amazonOrange" />
                <h2 className="text-lg font-bold text-amazonInk">Payment method</h2>
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-3">
                {[
                  ["card", "Fake card", "4111 1111 1111 1111"],
                  ["upi", "Demo UPI", "rahul@amazonedge"],
                  ["cod", "COD", "Pay when delivered"],
                ].map(([value, label, detail]) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setPaymentMethod(value as PaymentMethod)}
                    className={`rounded-amazon border p-3 text-left text-sm shadow-sm ${
                      paymentMethod === value
                        ? "border-amazonOrange bg-orange-50"
                        : "border-gray-300 bg-white hover:bg-amazonBg"
                    }`}
                  >
                    <span className="block font-bold text-amazonInk">{label}</span>
                    <span className="mt-1 block text-xs text-gray-600">{detail}</span>
                  </button>
                ))}
              </div>
              <div className="mt-4 max-w-xs">
                <PrimaryButton onClick={() => placeOrder(paymentMethod)}>
                  {paymentMethod === "cod" ? (
                    <span className="inline-flex items-center gap-2">
                      <IndianRupee className="h-4 w-4" />
                      Place COD order
                    </span>
                  ) : (
                    "Place demo order"
                  )}
                </PrimaryButton>
              </div>
            </section>
          </div>

          <aside className="lg:col-span-4">
            <div className="rounded-amazon border border-gray-300 bg-white p-4 shadow-sm">
              <h2 className="text-lg font-bold text-amazonInk">Order summary</h2>
              <ul className="mt-3 space-y-3">
                {items.map((item) => (
                  <li key={item.id} className="flex gap-3">
                    <ProductImage
                      src={productImageSrc(item.product)}
                      alt={item.product.name}
                      className="aspect-square w-14 shrink-0"
                    />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-amazonInk">
                        {item.product.name}
                      </p>
                      <p className="text-xs text-gray-600">
                        {inr.format(cartLinePrice(item))}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
              <dl className="mt-4 space-y-2 border-t border-gray-200 pt-3 text-sm">
                <div className="flex justify-between">
                  <dt>Items</dt>
                  <dd>{inr.format(totals.subtotal)}</dd>
                </div>
                <div className="flex justify-between text-green-800">
                  <dt>Discount</dt>
                  <dd>-{inr.format(totals.discount)}</dd>
                </div>
                <div className="flex justify-between border-t border-gray-200 pt-2 text-base font-bold">
                  <dt>Total</dt>
                  <dd>{inr.format(totals.total)}</dd>
                </div>
              </dl>
            </div>
          </aside>
        </div>
      )}
    </section>
  );
}
