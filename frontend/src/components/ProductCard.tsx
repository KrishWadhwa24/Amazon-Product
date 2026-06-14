import Link from "next/link";

import { ProductImage } from "@/components/ProductImage";
import { StarRating } from "@/components/StarRating";
import { inr, productImageSrc, type Product } from "@/lib/catalog";

/**
 * A single Amazon-style catalog product card.
 *
 * The whole card links to the product detail page `/product/[asin]`. It shows
 * the product image (with placeholder fallback via {@link ProductImage}), the
 * name in the amazonLink color, the rating stars (amazonOrange) with the review
 * count, and the price in ₹ INR.
 */
export function ProductCard({ product }: { product: Product }) {
  return (
    <li className="rounded-amazon border border-gray-200 bg-white p-3 shadow-sm transition-shadow hover:shadow-md">
      <Link
        href={`/product/${encodeURIComponent(product.asin)}`}
        className="block focus:outline-none focus-visible:ring-2 focus-visible:ring-amazonOrange"
      >
        <ProductImage
          src={productImageSrc(product)}
          alt={product.name}
          className="aspect-square w-full"
        />
        <h2 className="mt-3 line-clamp-2 text-sm font-medium text-amazonLink hover:text-amazonOrange">
          {product.name}
        </h2>
      </Link>

      <div className="mt-1">
        <StarRating rating={product.rating} reviewCount={product.review_count} />
      </div>

      <p className="mt-1 text-lg font-bold text-amazonInk">
        {inr.format(product.price)}
      </p>
    </li>
  );
}
