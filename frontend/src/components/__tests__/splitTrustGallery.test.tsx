import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  LIVE_CONDITION_LABEL,
  SplitTrustGallery,
} from "@/components/SplitTrustGallery";

/**
 * Snapshot + structure tests for the Split-Trust gallery (Requirement 12.8).
 *
 * The gallery pairs the official Amazon catalog image (PRIMARY, trusted
 * reference) with the captured "live condition" photo (SECONDARY thumbnail
 * badged "Live Condition"). These tests assert:
 *  - the official image (primary, via ProductImage) uses the official src,
 *  - the condition thumbnail uses the provided condition image URL,
 *  - the "Live Condition" badge text is present,
 *  - and the rendered structure is captured in a snapshot.
 */

const OFFICIAL_SRC = "https://example.com/official-catalog.jpg";
const CONDITION_SRC = "https://example.com/live-condition.jpg";
const PRODUCT_NAME = "Sony WH-CH520 Wireless Headphones";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SplitTrustGallery — Split-Trust layout (Req 12.8)", () => {
  it("renders the official image as primary, the condition thumbnail, and the Live Condition badge", () => {
    const { container } = render(
      <SplitTrustGallery
        officialImageSrc={OFFICIAL_SRC}
        conditionImageUrl={CONDITION_SRC}
        productName={PRODUCT_NAME}
      />,
    );

    // The gallery root is present.
    expect(screen.getByTestId("split-trust-gallery")).toBeInTheDocument();

    // The official catalog image (primary + thumbnail) uses the official src.
    const officialImages = screen.getAllByAltText(
      /official Amazon catalog image/i,
    ) as HTMLImageElement[];
    expect(officialImages.length).toBeGreaterThanOrEqual(1);
    expect(
      officialImages.some((img) => img.getAttribute("src") === OFFICIAL_SRC),
    ).toBe(true);
    // The official image is NOT a placeholder fallback.
    expect(
      officialImages.some(
        (img) => img.getAttribute("data-placeholder") === "false",
      ),
    ).toBe(true);

    // The live-condition photo uses the provided condition image URL.
    const conditionImage = screen.getByAltText(
      /live condition photo/i,
    ) as HTMLImageElement;
    expect(conditionImage.getAttribute("src")).toBe(CONDITION_SRC);
    expect(conditionImage.getAttribute("data-placeholder")).toBe("false");

    // The "Live Condition" badge text is present.
    expect(screen.getAllByText(LIVE_CONDITION_LABEL).length).toBeGreaterThanOrEqual(1);

    // Snapshot the rendered gallery.
    expect(container).toMatchSnapshot();
  });
});
