"use client";

/**
 * Local Verified Used Deals page (Requirements 12.4, 12.5, 12.6, 12.8).
 *
 * This is a PUBLIC page (no auth required to browse): any visitor can see the
 * resale marketplace. On mount it fetches `GET /api/resale/feed` (ACTIVE
 * listings, newest first, each joined with its Product and original purchase
 * date) and renders the grid titled "Amazon Local Verified Used Deals"
 * (Req 12.4).
 *
 * Each card renders a {@link SplitTrustGallery} (official catalog image as
 * primary + live-condition photo as a badged secondary thumbnail — Req 12.8),
 * the product name (linking to the product page), the "✅ Amazon Verified
 * Original Purchase" badge and the Condition Grade (Req 12.6), the resale price
 * in ₹ INR, and the original purchase date.
 *
 * Buyers can act on a deal directly from the card:
 *  - "Add to Cart" → `POST /api/resale/{id}/cart` (adds the open-box line at the
 *    discounted resale price; the listing stays ACTIVE until bought).
 *  - "Buy Now"     → `POST /api/resale/{id}/buy` (marks the listing SOLD; it
 *    leaves the marketplace feed). Both require an authenticated buyer.
 *
 * When the feed is empty the titled grid is shown in a friendly empty state
 * rather than an error (Req 12.5). Loading and error states are handled too.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { BadgeCheck, ShieldCheck } from "lucide-react";

import { PrimaryButton } from "@/components/PrimaryButton";
import { SplitTrustGallery } from "@/components/SplitTrustGallery";
import { useAuthSession } from "@/context/AuthSessionContext";
import { ApiError, api } from "@/lib/api";

/** Condition grade as constrained by the backend (Req 12.6). */
type ConditionGrade = "Like New" | "Good" | "Fair";

/** Product fields needed by the Split-Trust gallery (mirrors backend). */
interface FeedProduct {
  asin: string;
  name: string;
  price: number;
  image_url: string;
  uploaded_image_path: string | null;
}

/** A single entry from `GET /api/resale/feed`. */
interface ResaleFeedItem {
  id: number;
  condition_grade: ConditionGrade;
  resale_price: number;
  /** Base price + ₹50 Amazon Commission — the final price shown to the buyer. */
  buyer_total_price: number;
  status: string;
  listed_at: string;
  condition_image_url: string;
  original_purchased_at: string;
  product: FeedProduct;
}

/** A transient confirmation/error banner shown after a buy/add-to-cart action. */
interface DealsBanner {
  kind: "success" | "error";
  message: string;
}

const PAGE_TITLE = "Amazon Local Verified Used Deals";

const currency = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 2,
});

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString("en-IN", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

/** Colour-codes the condition grade pill while keeping it readable. */
function gradeClasses(grade: ConditionGrade): string {
  switch (grade) {
    case "Like New":
      return "border-green-700 bg-green-50 text-green-800";
    case "Good":
      return "border-amazonLink bg-sky-50 text-amazonLink";
    case "Fair":
    default:
      return "border-amber-600 bg-amber-50 text-amber-700";
  }
}

/** A single resale deal card. */
function DealCard({
  item,
  signedIn,
  busy,
  onAddToCart,
  onBuyNow,
}: {
  item: ResaleFeedItem;
  signedIn: boolean;
  busy: boolean;
  onAddToCart: (item: ResaleFeedItem) => void;
  onBuyNow: (item: ResaleFeedItem) => void;
}) {
  const { product } = item;
  return (
    <li className="flex flex-col rounded-amazon border border-gray-300 bg-white p-3 shadow-sm">
      <SplitTrustGallery
        officialImageSrc={product.uploaded_image_path || product.image_url}
        conditionImageUrl={item.condition_image_url}
        productName={product.name}
      />

      <Link
        href={`/product/${encodeURIComponent(product.asin)}`}
        className="mt-3 line-clamp-2 text-sm font-bold text-amazonLink hover:text-amazonOrange"
      >
        {product.name}
      </Link>

      {/* Verified original purchase badge (Req 12.6). */}
      <p className="mt-2 inline-flex items-center gap-1 text-xs font-bold text-green-800">
        <BadgeCheck className="h-4 w-4 shrink-0" aria-hidden="true" />
        <span>✅ Amazon Verified Original Purchase</span>
      </p>

      {/* Final price = base + ₹50 Amazon Commission. */}
      <p className="mt-2 text-lg font-bold text-amazonInk">
        {currency.format(Number(item.buyer_total_price))}
      </p>
      <p className="mt-0.5 text-xs text-gray-500">
        Base {currency.format(Number(item.resale_price))} + ₹50 Amazon Commission
      </p>

      {/* Original purchase date — evidence of the verified original purchase. */}
      <p className="mt-1 text-xs text-gray-600">
        Original purchase: {formatDate(item.original_purchased_at)}
      </p>

      {/* Buyer actions. */}
      <div className="mt-3 space-y-2">
        {signedIn ? (
          <>
            <PrimaryButton disabled={busy} onClick={() => onBuyNow(item)}>
              {busy ? "Processing…" : "Buy Now"}
            </PrimaryButton>
            <button
              type="button"
              disabled={busy}
              onClick={() => onAddToCart(item)}
              className="inline-flex w-full items-center justify-center rounded-amazon border border-gray-400 bg-white px-4 py-2 text-sm font-medium text-amazonInk shadow-sm hover:bg-amazonBg focus:outline-none focus-visible:ring-2 focus-visible:ring-amazonOrange disabled:cursor-not-allowed disabled:opacity-60"
            >
              Add to Cart
            </button>
          </>
        ) : (
          <Link href="/login">
            <PrimaryButton>Sign in to buy</PrimaryButton>
          </Link>
        )}
      </div>
    </li>
  );
}

export default function LocalDealsPage() {
  const { user } = useAuthSession();
  const signedIn = user !== null;

  const [deals, setDeals] = useState<ResaleFeedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [banner, setBanner] = useState<DealsBanner | null>(null);
  // The listing id with an action in flight, so we can disable just that card.
  const [busyId, setBusyId] = useState<number | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await api.get<ResaleFeedItem[]>("/api/resale/feed");
        if (active) setDeals(data ?? []);
      } catch {
        if (active) {
          setError("We couldn't load local deals right now. Please try again.");
        }
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  async function handleBuyNow(item: ResaleFeedItem) {
    setBanner(null);
    setBusyId(item.id);
    try {
      await api.post(`/api/resale/${item.id}/buy`);
      // The listing is SOLD — drop it from the visible feed immediately.
      setDeals((prev) => prev.filter((d) => d.id !== item.id));
      setBanner({
        kind: "success",
        message: `Purchased ${item.product.name} (${item.condition_grade}) for ${currency.format(
          Number(item.buyer_total_price),
        )}. It's on its way!`,
      });
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : "We couldn't complete your purchase. Please try again.";
      setBanner({ kind: "error", message });
    } finally {
      setBusyId(null);
    }
  }

  async function handleAddToCart(item: ResaleFeedItem) {
    setBanner(null);
    setBusyId(item.id);
    try {
      await api.post(`/api/resale/${item.id}/cart`);
      setBanner({
        kind: "success",
        message: `Added ${item.product.name} (open-box, ${item.condition_grade}) to your cart.`,
      });
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : "We couldn't add this deal to your cart. Please try again.";
      setBanner({ kind: "error", message });
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section className="space-y-4">
      <header>
        <h1 className="text-2xl font-bold text-amazonInk">{PAGE_TITLE}</h1>
        <p className="mt-1 text-sm text-gray-600">
          Open-box and pre-owned items from verified original purchases, near
          you.
        </p>
      </header>

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

      {loading ? (
        <p className="text-sm text-amazonInk">Loading local deals…</p>
      ) : error ? (
        <div
          role="alert"
          className="rounded border border-red-600 bg-red-50 p-3 text-sm text-red-700"
        >
          {error}
        </div>
      ) : deals.length === 0 ? (
        // Empty state — titled grid without error (Req 12.5).
        <div className="rounded-amazon border border-gray-300 bg-white p-8 text-center shadow-sm">
          <p className="text-base font-bold text-amazonInk">
            No local deals available yet
          </p>
          <p className="mx-auto mt-1 max-w-md text-sm text-gray-600">
            Verified used items listed by sellers near you will appear here.
            Check back soon for open-box savings.
          </p>
        </div>
      ) : (
        <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4">
          {deals.map((item) => (
            <DealCard
              key={item.id}
              item={item}
              signedIn={signedIn}
              busy={busyId === item.id}
              onAddToCart={handleAddToCart}
              onBuyNow={handleBuyNow}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
