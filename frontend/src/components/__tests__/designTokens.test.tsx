import { describe, expect, it, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { NavBar } from "../NavBar";
import { PrimaryButton } from "../PrimaryButton";
import { AuthSessionProvider } from "@/context/AuthSessionContext";

// NavBar consumes the auth session context, so render it inside the provider.
// Stub fetch so the provider's on-mount session hydration resolves to "signed
// out" deterministically without hitting the network.
beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(JSON.stringify({ error: { code: "NO_SESSION", message: "no" } }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
});

/** Render a node wrapped in the AuthSessionProvider. */
function renderWithAuth(node: ReactElement) {
  return render(<AuthSessionProvider>{node}</AuthSessionProvider>);
}

/**
 * Snapshot / style + contrast tests for the Amazon design tokens (Req 17.1, 17.2, 17.4).
 *
 * These validate the visual shell tokens without exercising input-dependent
 * behavior: appearance does not vary meaningfully with input, so snapshots plus
 * targeted class assertions (gradient/radius/navy band) are the right tool. The
 * contrast check computes the deterministic WCAG ratio for body text.
 */

// --- Tiny WCAG contrast helper (relative luminance per WCAG 2.x) ---

/** Parse a #RRGGBB hex color into 8-bit RGB channels. */
function hexToRgb(hex: string): [number, number, number] {
  const clean = hex.replace("#", "");
  const r = parseInt(clean.slice(0, 2), 16);
  const g = parseInt(clean.slice(2, 4), 16);
  const b = parseInt(clean.slice(4, 6), 16);
  return [r, g, b];
}

/** Relative luminance of a single sRGB channel value in [0, 255]. */
function channelLuminance(value: number): number {
  const c = value / 255;
  return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

/** WCAG relative luminance of a color. */
function relativeLuminance(hex: string): number {
  const [r, g, b] = hexToRgb(hex);
  return (
    0.2126 * channelLuminance(r) +
    0.7152 * channelLuminance(g) +
    0.0722 * channelLuminance(b)
  );
}

/** WCAG contrast ratio between two colors (>= 1, max 21). */
function contrastRatio(fg: string, bg: string): number {
  const l1 = relativeLuminance(fg);
  const l2 = relativeLuminance(bg);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

// Design tokens under test (mirror tailwind.config.ts).
const AMAZON_INK = "#0F1111"; // body text on customer pages
const AMAZON_BG = "#EAEDED"; // page background
const WHITE = "#FFFFFF"; // card/surface background

describe("Design tokens — snapshots", () => {
  it("matches the NavBar snapshot", () => {
    const { container } = renderWithAuth(<NavBar />);
    expect(container.firstChild).toMatchSnapshot();
  });

  it("matches the PrimaryButton snapshot", () => {
    const { container } = render(<PrimaryButton>Add to Cart</PrimaryButton>);
    expect(container.firstChild).toMatchSnapshot();
  });
});

describe("PrimaryButton — gradient/radius tokens (Req 17.2)", () => {
  it("carries the gradient and radius token classes and a dark border", () => {
    const { getByRole } = render(<PrimaryButton>Buy Now</PrimaryButton>);
    const button = getByRole("button", { name: "Buy Now" });

    // Gradient token (#FFD814 -> #F7CA00) and 8px radius token.
    expect(button.className).toContain("bg-amazon-button");
    expect(button.className).toContain("rounded-amazon");
    // Dark border for definition against light backgrounds.
    expect(button.className).toContain("border");
    expect(button.className).toContain("border-[#a88734]/60");
  });
});

describe("NavBar — token bands (Req 17.1)", () => {
  it("uses the navy top bar and the secondary dark band", () => {
    const { container } = renderWithAuth(<NavBar />);

    // Navy top bar token (#232F3E).
    expect(container.querySelector(".bg-amazonNavy")).not.toBeNull();
    // Secondary dark band token (#131921).
    expect(container.querySelector(".bg-amazonDark")).not.toBeNull();
  });
});

describe("Body-text contrast (Req 17.4)", () => {
  it("amazonInk on amazonBg meets WCAG AA (>= 4.5:1)", () => {
    expect(contrastRatio(AMAZON_INK, AMAZON_BG)).toBeGreaterThanOrEqual(4.5);
  });

  it("amazonInk on white meets WCAG AA (>= 4.5:1)", () => {
    expect(contrastRatio(AMAZON_INK, WHITE)).toBeGreaterThanOrEqual(4.5);
  });

  it("contrast helper computes the known black-on-white maximum (21:1)", () => {
    // Sanity check on the helper itself against the WCAG reference maximum.
    expect(contrastRatio("#000000", "#FFFFFF")).toBeCloseTo(21, 1);
  });
});
