"use client";

/**
 * Home / catalog page (Requirements 4.x buyer surface).
 *
 * On mount it fetches `GET /api/products` and renders an Amazon-style product
 * grid ({@link ProductGrid} / {@link ProductCard}). Each card links to the
 * product detail page `/product/[asin]`. This is a PUBLIC page — browsing the
 * catalog does not require authentication; the purchase-intent actions on the
 * product detail page are what require a session.
 */

import { useEffect, useState } from "react";

import { ProductGrid } from "@/components/ProductGrid";
import { api } from "@/lib/api";
import type { Product } from "@/lib/catalog";

export default function HomePage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);

    (async () => {
      try {
        const data = await api.get<Product[]>("/api/products");
        if (active) setProducts(data ?? []);
      } catch {
        if (active) {
          setError("We couldn't load the catalog right now. Please try again.");
        }
      } finally {
        if (active) setLoading(false);
      }
    })();

    return () => {
      active = false;
    };
  }, []);

  return (
    <section className="space-y-4">
      <header>
        <h1 className="text-2xl font-bold text-amazonInk">
          Today&apos;s deals on Amazon Edge-Return
        </h1>
        <p className="mt-1 text-sm text-gray-600">
          Browse the catalog. Returned items nearby may unlock instant local
          open-box deals when you show interest.
        </p>
      </header>

      {loading ? (
        <p className="text-sm text-amazonInk">Loading products…</p>
      ) : error ? (
        <div
          role="alert"
          className="rounded border border-red-600 bg-red-50 p-3 text-sm text-red-700"
        >
          {error}
        </div>
      ) : products.length === 0 ? (
        <div className="rounded-amazon border border-gray-300 bg-white p-8 text-center text-sm text-amazonInk shadow-sm">
          No products are available right now.
        </div>
      ) : (
        <ProductGrid products={products} />
      )}
    </section>
  );
}
