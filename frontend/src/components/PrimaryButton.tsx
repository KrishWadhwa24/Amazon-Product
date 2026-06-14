import type { ButtonHTMLAttributes, ReactNode } from "react";

type PrimaryButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode;
};

/**
 * Amazon-style primary action button (Req 17.2).
 *
 * - 8px radius on all corners (`rounded-amazon`).
 * - Top-to-bottom gradient #FFD814 -> #F7CA00 (`bg-amazon-button`).
 * - Subtle dark border for definition against light backgrounds.
 *
 * Reused by product BuyBox, cart, and other customer-facing actions.
 */
export function PrimaryButton({
  children,
  className = "",
  type = "button",
  ...rest
}: PrimaryButtonProps) {
  return (
    <button
      type={type}
      className={[
        "inline-flex w-full items-center justify-center",
        "rounded-amazon bg-amazon-button",
        "border border-[#a88734]/60",
        "px-4 py-2 text-sm font-medium text-amazonInk",
        "shadow-sm transition-[filter] hover:brightness-95",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-amazonOrange",
        "disabled:cursor-not-allowed disabled:opacity-60",
        className,
      ].join(" ")}
      {...rest}
    >
      {children}
    </button>
  );
}
