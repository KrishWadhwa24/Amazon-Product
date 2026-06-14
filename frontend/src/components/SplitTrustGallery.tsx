"use client";

/**
 * Split-Trust image gallery (Requirement 12.8).
 *
 * Pairs the idealized, trusted catalog photo with the actual captured photo of
 * the item so buyers can judge the real condition against the official
 * reference. The official `Product.image_url` (preferring an
 * `uploaded_image_path` when present) is shown as the PRIMARY image; the
 * listing's `condition_image_url` is shown as a SECONDARY thumbnail badged
 * "Live Condition".
 *
 * Selecting the "Live Condition" thumbnail swaps it into the primary view (and
 * the official image becomes the selectable secondary), but the structure
 * always clearly presents both: a primary view and a secondary thumbnail, with
 * the "Live Condition" badge attached to the condition image wherever it is
 * rendered.
 *
 * The official image uses {@link ProductImage} for graceful placeholder
 * fallback. The condition image is a captured photo rendered with an `<img>`
 * plus an `onError` fallback to the same bundled placeholder.
 */
import { useEffect, useState } from "react";

import { PLACEHOLDER_PRODUCT_SRC, ProductImage } from "@/components/ProductImage";

/** Badge text mandated by Requirement 12.8 for the condition image. */
export const LIVE_CONDITION_LABEL = "Live Condition";

export interface SplitTrustGalleryProps {
  /**
   * The official catalog image source. Pass the product's
   * `uploaded_image_path` when present, otherwise its `image_url`. When empty
   * the bundled placeholder is shown (via {@link ProductImage}).
   */
  officialImageSrc?: string | null;
  /**
   * The captured "live condition" photo URL from the resale listing's
   * `condition_image_url`. Rendered with a graceful `onError` fallback.
   */
  conditionImageUrl: string;
  /** Accessible name for the product (used to build image alt text). */
  productName: string;
  /** Optional wrapper classes. */
  className?: string;
}

/** Which image currently occupies the primary view. */
type PrimaryView = "official" | "condition";

/** Small "Live Condition" pill badge. */
function LiveConditionBadge({ className = "" }: { className?: string }) {
  return (
    <span
      className={[
        "pointer-events-none absolute left-1 top-1 z-10 rounded",
        "bg-amazonNavy/90 px-1.5 py-0.5 text-[10px] font-bold uppercase",
        "tracking-wide text-white shadow",
        className,
      ].join(" ")}
    >
      {LIVE_CONDITION_LABEL}
    </span>
  );
}

/**
 * The captured condition photo. Falls back to the bundled placeholder if the
 * image fails to load (the condition image is a captured photo, not a curated
 * catalog asset).
 */
function ConditionImage({
  src,
  alt,
  className = "",
  imgClassName = "",
}: {
  src: string;
  alt: string;
  className?: string;
  imgClassName?: string;
}) {
  const [currentSrc, setCurrentSrc] = useState<string>(
    src && src.trim().length > 0 ? src : PLACEHOLDER_PRODUCT_SRC,
  );

  useEffect(() => {
    setCurrentSrc(src && src.trim().length > 0 ? src : PLACEHOLDER_PRODUCT_SRC);
  }, [src]);

  const isPlaceholder = currentSrc === PLACEHOLDER_PRODUCT_SRC;

  return (
    <span
      className={["block overflow-hidden rounded-amazon bg-white", className].join(
        " ",
      )}
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

export function SplitTrustGallery({
  officialImageSrc,
  conditionImageUrl,
  productName,
  className = "",
}: SplitTrustGalleryProps) {
  // The official catalog image is the default primary (trusted reference).
  const [primary, setPrimary] = useState<PrimaryView>("official");

  const officialAlt = `${productName} — official Amazon catalog image`;
  const conditionAlt = `${productName} — live condition photo`;

  return (
    <div className={["flex flex-col gap-2", className].join(" ")} data-testid="split-trust-gallery">
      {/* Primary view */}
      <div className="relative aspect-square w-full">
        {primary === "official" ? (
          <ProductImage
            src={officialImageSrc}
            alt={officialAlt}
            className="aspect-square w-full"
          />
        ) : (
          <>
            <LiveConditionBadge />
            <ConditionImage
              src={conditionImageUrl}
              alt={conditionAlt}
              className="aspect-square w-full"
            />
          </>
        )}
      </div>

      {/* Secondary thumbnails: official + live condition. The thumbnail that is
          NOT currently primary is the obvious selectable swap target, but both
          are rendered so the split (official + live condition) is always
          clearly presented. */}
      <ul className="flex items-center gap-2">
        <li>
          <button
            type="button"
            onClick={() => setPrimary("official")}
            aria-pressed={primary === "official"}
            aria-label="View official Amazon catalog image"
            className={[
              "block h-14 w-14 overflow-hidden rounded-amazon border bg-white",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-amazonOrange",
              primary === "official"
                ? "border-amazonOrange ring-1 ring-amazonOrange"
                : "border-gray-300 hover:border-amazonLink",
            ].join(" ")}
          >
            <ProductImage
              src={officialImageSrc}
              alt={officialAlt}
              className="h-full w-full"
            />
          </button>
        </li>
        <li>
          <div className="relative">
            <LiveConditionBadge />
            <button
              type="button"
              onClick={() => setPrimary("condition")}
              aria-pressed={primary === "condition"}
              aria-label="View live condition photo"
              className={[
                "block h-14 w-14 overflow-hidden rounded-amazon border bg-white",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-amazonOrange",
                primary === "condition"
                  ? "border-amazonOrange ring-1 ring-amazonOrange"
                  : "border-gray-300 hover:border-amazonLink",
              ].join(" ")}
            >
              <ConditionImage
                src={conditionImageUrl}
                alt={conditionAlt}
                className="h-full w-full"
              />
            </button>
          </div>
        </li>
      </ul>
    </div>
  );
}
