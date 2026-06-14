import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { PLACEHOLDER_PRODUCT_SRC, ProductImage } from "./ProductImage";

describe("ProductImage", () => {
  it("renders the provided src when present", () => {
    render(<ProductImage src="https://example.com/p.jpg" alt="A product" />);
    const img = screen.getByAltText("A product");
    expect(img).toHaveAttribute("src", "https://example.com/p.jpg");
    expect(img).toHaveAttribute("data-placeholder", "false");
  });

  it("falls back to the placeholder when src is null", () => {
    render(<ProductImage src={null} alt="Demo product" />);
    const img = screen.getByAltText("Demo product");
    expect(img).toHaveAttribute("src", PLACEHOLDER_PRODUCT_SRC);
    expect(img).toHaveAttribute("data-placeholder", "true");
  });

  it("falls back to the placeholder when src is empty/whitespace", () => {
    render(<ProductImage src="   " alt="Empty src" />);
    const img = screen.getByAltText("Empty src");
    expect(img).toHaveAttribute("src", PLACEHOLDER_PRODUCT_SRC);
    expect(img).toHaveAttribute("data-placeholder", "true");
  });

  it("swaps to the placeholder when the image fails to load (onError)", () => {
    render(<ProductImage src="https://example.com/broken.jpg" alt="Broken" />);
    const img = screen.getByAltText("Broken");
    expect(img).toHaveAttribute("src", "https://example.com/broken.jpg");

    fireEvent.error(img);

    expect(img).toHaveAttribute("src", PLACEHOLDER_PRODUCT_SRC);
    expect(img).toHaveAttribute("data-placeholder", "true");
  });
});
