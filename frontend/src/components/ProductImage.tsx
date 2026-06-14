"use client";

import { useEffect, useState } from "react";

/** Bundled fallback asset shown until real product photos are uploaded. */
export const PLACEHOLDER_PRODUCT_SRC = "/placeholder-product.svg";

type ProductImageProps = {
  /**
   * The product image source. Accepts an `uploaded_image_path` or `image_url`.
   * When empty/null/undefined the bundled placeholder is shown instead.
   */
  src?: string | null;
  /** Accessible alt text for the image. */
  alt: string;
  /** Optional wrapper classes (e.g. sizing/aspect ratio). */
  className?: string;
  /** Optional classes applied to the rendered <img>. */
  imgClassName?: string;
};

function isUsableSrc(src?: string | null): src is string {
  return typeof src === "string" && src.trim().length > 0;
}

/**
 * Renders a product's image with a graceful placeholder fallback.
 *
 * The placeholder is shown when:
 *  - `src` is empty, null, or undefined, or
 *  - the image fails to load (onError).
 *
 * This is reused by the catalog, product detail, orders, local-deals, and admin
 * surfaces. Until real product photos are uploaded, pass `src={null}` (or omit
 * it) to display the "Image coming soon" demo placeholder.
 */
export function ProductImage({
  src,
  alt,
  className = "",
  imgClassName = "",
}: ProductImageProps) {
  const initialSrc = isUsableSrc(src) ? src : PLACEHOLDER_PRODUCT_SRC;
  const [currentSrc, setCurrentSrc] = useState<string>(initialSrc);

  // Keep in sync if the incoming src prop changes (e.g. async data load).
  useEffect(() => {
    setCurrentSrc(isUsableSrc(src) ? src : PLACEHOLDER_PRODUCT_SRC);
  }, [src]);

  const isPlaceholder = currentSrc === PLACEHOLDER_PRODUCT_SRC;

  return (
    <span
      className={[
        "block overflow-hidden rounded-amazon bg-white",
        className,
      ].join(" ")}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={currentSrc}
        alt={alt}
        data-placeholder={isPlaceholder ? "true" : "false"}
        onError={() => {
          if (currentSrc !== PLACEHOLDER_PRODUCT_SRC) {
            setCurrentSrc(PLACEHOLDER_PRODUCT_SRC);
          }
        }}
        className={["h-full w-full object-contain", imgClassName].join(" ")}
      />
    </span>
  );
}
