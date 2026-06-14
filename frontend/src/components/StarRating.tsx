import { Star } from "lucide-react";

type StarRatingProps = {
  /** Average rating in [0.0, 5.0]. */
  rating: number;
  /** Number of reviews shown alongside the stars. */
  reviewCount?: number;
  /** Optional wrapper classes. */
  className?: string;
};

const STAR_COUNT = 5;

function clampRating(rating: number): number {
  if (Number.isNaN(rating)) return 0;
  return Math.min(STAR_COUNT, Math.max(0, rating));
}

/**
 * Amazon-style rating stars rendered in the amazonOrange accent token
 * (Req 17.1), followed by the review count.
 *
 * Five star outlines are overlaid with a clipped amazonOrange fill whose width
 * is proportional to the rating, so fractional ratings (e.g. 4.3) render a
 * partially filled star. The review count is shown in the amazonLink color to
 * match Amazon's "(1,234)" review links.
 */
export function StarRating({
  rating,
  reviewCount,
  className = "",
}: StarRatingProps) {
  const value = clampRating(rating);
  const fillPercent = (value / STAR_COUNT) * 100;
  const label = `${value.toFixed(1)} out of 5 stars`;

  return (
    <span
      className={["inline-flex items-center gap-1", className].join(" ")}
      aria-label={
        reviewCount === undefined
          ? label
          : `${label}, ${reviewCount} reviews`
      }
    >
      <span className="relative inline-block leading-none" role="img" aria-hidden="true">
        {/* Empty star outlines */}
        <span className="flex text-gray-300">
          {Array.from({ length: STAR_COUNT }).map((_, i) => (
            <Star key={i} className="h-4 w-4" aria-hidden="true" />
          ))}
        </span>
        {/* Filled overlay clipped to the rating width */}
        <span
          className="absolute inset-0 flex overflow-hidden text-amazonOrange"
          style={{ width: `${fillPercent}%` }}
        >
          {Array.from({ length: STAR_COUNT }).map((_, i) => (
            <Star
              key={i}
              className="h-4 w-4 shrink-0 fill-current"
              aria-hidden="true"
            />
          ))}
        </span>
      </span>
      {reviewCount !== undefined ? (
        <span className="text-xs font-medium text-amazonLink">
          {reviewCount.toLocaleString("en-IN")}
        </span>
      ) : null}
    </span>
  );
}
