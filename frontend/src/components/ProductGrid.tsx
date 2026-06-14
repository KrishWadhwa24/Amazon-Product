import { ProductCard } from "@/components/ProductCard";
import type { Product } from "@/lib/catalog";

/**
 * Amazon-style responsive product grid. Renders a {@link ProductCard} for each
 * product, scaling from two columns on mobile up to five on large screens.
 */
export function ProductGrid({ products }: { products: Product[] }) {
  return (
    <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
      {products.map((product) => (
        <ProductCard key={product.asin} product={product} />
      ))}
    </ul>
  );
}
