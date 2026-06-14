import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { MatchNotificationPopup } from "../MatchNotificationPopup";
import { inr } from "@/lib/catalog";
import {
  LOCAL_DEAL_HEADLINE,
  LOCAL_DEAL_SUBHEADLINE,
  type MatchNotification,
} from "@/lib/notifications";

/**
 * Unit tests for the presentational match-notification popup
 * (Requirements 7.4, 8.2, 8.3, 8.4, 8.5, 18.3).
 *
 * `MatchNotificationPopup` is purely presentational: it always receives a
 * notification (the poller renders nothing while none exists — Req 8.3) and
 * surfaces the deal headline + supporting line, the matched product, the money
 * saved, the delivery time saved, and — only when the backend includes it
 * (>= 0.1 kg, Req 7.3) — the carbon avoided. Two actions, "Claim Deal" and
 * "Keep Original Delivery", are always visible and enabled unless `busy`
 * (Req 7.4, 8.2). The actual hide-within-1s behavior (Req 8.4, 8.5) is owned by
 * the poller and exercised in notificationPoller.test.tsx; here we assert the
 * action callbacks fire so the poller can react.
 */

/** A representative PENDING notification with carbon present (>= 0.1 kg). */
function buildNotification(
  overrides: Partial<MatchNotification> = {},
): MatchNotification {
  return {
    candidate_id: 1,
    headline: LOCAL_DEAL_HEADLINE,
    money_saved: 450,
    delivery_time_saved_hours: 36,
    carbon_avoided_kg: 2.5,
    distance_km: 3.2,
    product: {
      name: "Sony WH-CH520 Wireless Headphones",
      asin: "B09ZS3R8D2",
      image_url: "https://example.com/sony.jpg",
      uploaded_image_path: null,
    },
    ...overrides,
  };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("MatchNotificationPopup — rendering (Req 8.2, 7.4)", () => {
  it("renders the headline, subheadline, product, money saved, delivery time, and carbon", () => {
    render(
      <MatchNotificationPopup
        notification={buildNotification()}
        onClaim={vi.fn()}
        onKeepOriginal={vi.fn()}
      />,
    );

    const dialog = screen.getByRole("dialog");
    const scope = within(dialog);

    // Deal headline (Req 8.2 / 18.3) and supporting line (Req 8.2).
    expect(
      scope.getByRole("heading", { name: LOCAL_DEAL_HEADLINE }),
    ).toBeInTheDocument();
    expect(scope.getByText(LOCAL_DEAL_SUBHEADLINE)).toBeInTheDocument();

    // Matched product (image + name) and distance.
    expect(
      scope.getByText("Sony WH-CH520 Wireless Headphones"),
    ).toBeInTheDocument();
    expect(scope.getByText(/3\.20 km away/)).toBeInTheDocument();

    // Money saved equals the Local_Discount, formatted as ₹ currency (Req 7.2).
    expect(scope.getByText(inr.format(450))).toBeInTheDocument();

    // Delivery time saved as whole hours (Req 7.2).
    expect(scope.getByText(/36 hours sooner/)).toBeInTheDocument();

    // Carbon avoided is shown when present (>= 0.1 kg, Req 7.3).
    expect(scope.getByText(/CO₂ avoided/)).toBeInTheDocument();
    expect(scope.getByText(/2\.5 kg/)).toBeInTheDocument();
  });

  it("presents both 'Claim Deal' and 'Keep Original Delivery' actions, enabled (Req 7.4, 8.2)", () => {
    render(
      <MatchNotificationPopup
        notification={buildNotification()}
        onClaim={vi.fn()}
        onKeepOriginal={vi.fn()}
      />,
    );

    const claim = screen.getByRole("button", { name: "Claim Deal" });
    const keep = screen.getByRole("button", { name: /Keep Original Delivery/ });

    expect(claim).toBeInTheDocument();
    expect(keep).toBeInTheDocument();
    expect(claim).toBeEnabled();
    expect(keep).toBeEnabled();
  });

  it("disables both actions while an action is in flight (busy)", () => {
    render(
      <MatchNotificationPopup
        notification={buildNotification()}
        busy
        onClaim={vi.fn()}
        onKeepOriginal={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: /Claiming/ })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: /Keep Original Delivery/ }),
    ).toBeDisabled();
  });

  it("falls back to the default headline when none is provided", () => {
    render(
      <MatchNotificationPopup
        notification={buildNotification({ headline: "" })}
        onClaim={vi.fn()}
        onKeepOriginal={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("heading", { name: LOCAL_DEAL_HEADLINE }),
    ).toBeInTheDocument();
  });
});

describe("MatchNotificationPopup — carbon suppression (Req 7.3)", () => {
  it("omits the CO₂ line when carbon_avoided_kg is null", () => {
    render(
      <MatchNotificationPopup
        notification={buildNotification({ carbon_avoided_kg: null })}
        onClaim={vi.fn()}
        onKeepOriginal={vi.fn()}
      />,
    );

    expect(screen.queryByText(/CO₂ avoided/)).not.toBeInTheDocument();
  });

  it("omits the CO₂ line when carbon_avoided_kg is undefined", () => {
    render(
      <MatchNotificationPopup
        notification={buildNotification({ carbon_avoided_kg: undefined })}
        onClaim={vi.fn()}
        onKeepOriginal={vi.fn()}
      />,
    );

    expect(screen.queryByText(/CO₂ avoided/)).not.toBeInTheDocument();
  });
});

describe("MatchNotificationPopup — actions (Req 8.4, 8.5)", () => {
  it("invokes onClaim when 'Claim Deal' is clicked", async () => {
    const user = userEvent.setup();
    const onClaim = vi.fn();
    const onKeepOriginal = vi.fn();

    render(
      <MatchNotificationPopup
        notification={buildNotification()}
        onClaim={onClaim}
        onKeepOriginal={onKeepOriginal}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Claim Deal" }));

    expect(onClaim).toHaveBeenCalledTimes(1);
    expect(onKeepOriginal).not.toHaveBeenCalled();
  });

  it("invokes onKeepOriginal when 'Keep Original Delivery' is clicked", async () => {
    const user = userEvent.setup();
    const onClaim = vi.fn();
    const onKeepOriginal = vi.fn();

    render(
      <MatchNotificationPopup
        notification={buildNotification()}
        onClaim={onClaim}
        onKeepOriginal={onKeepOriginal}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: /Keep Original Delivery/ }),
    );

    expect(onKeepOriginal).toHaveBeenCalledTimes(1);
    expect(onClaim).not.toHaveBeenCalled();
  });
});
