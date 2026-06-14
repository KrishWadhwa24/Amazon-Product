"use client";

/**
 * Product detail page (Requirements 4.1–4.4).
 *
 * On mount it fetches `GET /api/products/{asin}` and renders a large product
 * image, the title, rating stars + review count, and the {@link BuyBox} with
 * the buyer purchase-intent actions (Add to Cart / Buy Now / Add to Wish List).
 *
 * It also fires `POST /api/view` once on load to record a "viewed" demand
 * signal (Req 4.4) — but only when a buyer is signed in. View recording is
 * best-effort: anonymous visitors are skipped, and any error is ignored so it
 * never blocks rendering the page. The view fire is keyed off the active user
 * id so switching users re-records the view for the new session (Req 1.7).
 */

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";

import { BuyBox } from "@/components/BuyBox";
import { ProductImage } from "@/components/ProductImage";
import { StarRating } from "@/components/StarRating";
import { useAuthSession } from "@/context/AuthSessionContext";
import { API_BASE, api } from "@/lib/api";
import { productImageSrc, type Product } from "@/lib/catalog";

export default function ProductDetailPage() {
  const params = useParams<{ asin: string }>();
  const asin = Array.isArray(params.asin) ? params.asin[0] : params.asin;
  const { user } = useAuthSession();

  const [product, setProduct] = useState<Product | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Track which (user, asin) pair has already had a view recorded so we fire
  // `POST /api/view` at most once per load/session-switch.
  const viewedKeyRef = useRef<string | null>(null);

  // Product-photo upload state.
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  // Fetch the product whenever the asin changes.
  useEffect(() => {
    if (!asin) return;
    let active = true;
    setLoading(true);
    setError(null);
    setProduct(null);

    (async () => {
      try {
        const data = await api.get<Product>(
          `/api/products/${encodeURIComponent(asin)}`,
        );
        if (active) setProduct(data);
      } catch {
        if (active) {
          setError("We couldn't find this product. It may no longer exist.");
        }
      } finally {
        if (active) setLoading(false);
      }
    })();

    return () => {
      active = false;
    };
  }, [asin]);

  // Record a "viewed" demand signal on load — only when signed in (Req 4.4).
  // Best-effort: skip anonymous visitors and ignore any error.
  useEffect(() => {
    if (!asin || !user) return;
    const key = `${user.user_id}:${asin}`;
    if (viewedKeyRef.current === key) return;
    viewedKeyRef.current = key;
    void api.post("/api/view", { asin }).catch(() => {
      // View recording is non-blocking; ignore failures.
    });
  }, [asin, user?.user_id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Upload a real product photo (multipart) and swap in the returned image.
  async function handleUpload(fileList: FileList | null) {
    const file = fileList?.[0];
    if (!file || !asin) return;
    setUploadError(null);
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(
        `${API_BASE}/api/products/${encodeURIComponent(asin)}/image`,
        { method: "POST", credentials: "include", body: form },
      );
      if (!res.ok) throw new Error(`Upload failed (${res.status})`);
      const updated = (await res.json()) as Product;
      setProduct(updated);
    } catch {
      setUploadError("We couldn't upload that image. Please try a JPEG or PNG.");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  if (loading) {
    return <p className="text-sm text-amazonInk">Loading product…</p>;
  }

  if (error || !product) {
    return (
      <section className="mx-auto max-w-md">
        <div className="rounded-amazon border border-gray-300 bg-white p-6 text-center shadow-sm">
          <h1 className="text-xl font-bold text-amazonInk">
            Product not found
          </h1>
          <p className="mt-2 text-sm text-amazonInk">
            {error ?? "This product is unavailable."}
          </p>
          <div className="mt-4">
            <Link
              href="/"
              className="text-sm font-medium text-amazonLink hover:text-amazonOrange"
            >
              Back to catalog
            </Link>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="grid grid-cols-1 gap-6 md:grid-cols-12">
      {/* Large product image */}
      <div className="md:col-span-5">
        <ProductImage
          src={productImageSrc(product)}
          alt={product.name}
          className="aspect-square w-full"
        />

        {/* Product photo uploader. The placeholder shows until a real photo is
            uploaded here; uploading swaps it in immediately. */}
        <div className="mt-3 rounded-amazon border border-dashed border-gray-300 bg-white p-3">
          <p className="text-xs font-bold text-amazonInk">Product photo</p>
          <p className="mt-0.5 text-xs text-gray-600">
            {product.uploaded_image_path
              ? "A custom photo is set. Upload again to replace it."
              : "Showing a demo placeholder. Upload a JPEG or PNG to set a real photo."}
          </p>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            disabled={uploading}
            onChange={(e) => void handleUpload(e.target.files)}
            className="mt-2 block w-full text-xs text-amazonInk file:mr-3 file:rounded-amazon file:border-0 file:bg-amazonBg file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-amazonInk hover:file:bg-gray-200"
          />
          {uploading ? (
            <p className="mt-2 text-xs text-amazonLink">Uploading…</p>
          ) : null}
          {uploadError ? (
            <p role="alert" className="mt-2 text-xs text-red-700">
              {uploadError}
            </p>
          ) : null}
        </div>
      </div>

      {/* Title, rating, ASIN */}
      <div className="md:col-span-4">
        <h1 className="text-2xl font-bold text-amazonInk">{product.name}</h1>
        <div className="mt-2">
          <StarRating
            rating={product.rating}
            reviewCount={product.review_count}
          />
        </div>
        <p className="mt-2 text-xs text-gray-600">ASIN: {product.asin}</p>
        <hr className="my-4 border-gray-200" />
        <p className="text-sm text-amazonInk">
          Genuine catalog item. If a buyer near you has returned this product,
          showing interest may unlock an instant local open-box deal.
        </p>
      </div>

      {/* BuyBox */}
      <div className="md:col-span-3">
        <BuyBox product={product} />
      </div>
    </section>
  );
}
