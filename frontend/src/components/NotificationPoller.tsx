"use client";

/**
 * Global match-notification poller (Requirements 1.8, 8.1, 8.3, 8.4, 8.5).
 *
 * Mounted once near the NavBar (see `app/layout.tsx`), this client component:
 *  - polls `GET /api/notifications` every {@link DEFAULT_POLL_INTERVAL_MS}
 *    (3s, Requirement 8.1) — but ONLY while a user is logged in. The interval
 *    is (re)armed on login/user switch and cleared on logout/unmount.
 *  - renders {@link MatchNotificationPopup} for the first PENDING notification,
 *    powering the Flow 18 demo: once a buyer adds a matching item to cart, the
 *    next poll (within 3s) surfaces the "🔥 Local Open-Box Deal" popup
 *    (Requirement 1.8).
 *  - renders nothing while no PENDING notification exists (Requirement 8.3).
 *  - on "Claim Deal" / "Keep Original Delivery", POSTs to the accept/reject
 *    endpoint, optimistically hides the popup immediately (within 1s —
 *    Requirements 8.4, 8.5), and refreshes notifications (Requirement 8.6).
 *
 * `pollIntervalMs` is a prop (default 3000) so the cadence is deterministically
 * testable under fake timers (task 21.4).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2 } from "lucide-react";

import { MatchNotificationPopup } from "@/components/MatchNotificationPopup";
import { useAuthSession } from "@/context/AuthSessionContext";
import { api } from "@/lib/api";
import { claimLocalDeal, CLAIMED_DEAL_DISCOUNT } from "@/lib/localOrders";
import { fetchNotifications, type MatchNotification } from "@/lib/notifications";

/** Default short-poll interval, 3 seconds (Requirement 8.1). */
export const DEFAULT_POLL_INTERVAL_MS = 3000;

export interface NotificationPollerProps {
  /**
   * Poll cadence in milliseconds. Defaults to {@link DEFAULT_POLL_INTERVAL_MS}
   * (3000). Exposed for deterministic testing.
   */
  pollIntervalMs?: number;
}

export function NotificationPoller({
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
}: NotificationPollerProps) {
  const { user } = useAuthSession();
  const userId = user?.user_id ?? null;

  const [notifications, setNotifications] = useState<MatchNotification[]>([]);
  const [actionInFlight, setActionInFlight] = useState(false);
  const [claimedMessage, setClaimedMessage] = useState<string | null>(null);

  // Guard against overlapping polls if a request runs longer than the interval.
  const pollingRef = useRef(false);

  const poll = useCallback(async () => {
    if (pollingRef.current) return;
    pollingRef.current = true;
    try {
      const items = await fetchNotifications();
      setNotifications(items);
    } catch {
      // Transient failure: keep the current view and retry on the next cycle
      // (Requirement 8.6). PENDING candidates persist server-side until
      // delivered or their return leaves SCANNING.
    } finally {
      pollingRef.current = false;
    }
  }, []);

  // Arm the 3s short-poll only while logged in; clear on logout/user switch
  // (Requirements 8.1, 1.7). The userId dependency restarts polling cleanly
  // when the active user changes and clears prior notifications.
  useEffect(() => {
    if (userId === null) {
      setNotifications([]);
      setClaimedMessage(null);
      return;
    }

    // Immediate first poll so a match surfaces within the 3s bound, then on
    // the configured cadence.
    void poll();
    const intervalId = setInterval(() => {
      void poll();
    }, pollIntervalMs);

    return () => {
      clearInterval(intervalId);
    };
  }, [userId, pollIntervalMs, poll]);

  useEffect(() => {
    if (!claimedMessage) return;
    const timeoutId = setTimeout(() => setClaimedMessage(null), 6000);
    return () => clearTimeout(timeoutId);
  }, [claimedMessage]);

  const respond = useCallback(
    async (notification: MatchNotification, action: "accept" | "reject") => {
      setActionInFlight(true);
      // Optimistically hide the popup immediately (Requirements 8.4, 8.5).
      setNotifications((prev) =>
        prev.filter((n) => n.candidate_id !== notification.candidate_id),
      );
      try {
        await api.post(`/api/matches/${notification.candidate_id}/${action}`);
        if (action === "accept" && userId !== null) {
          claimLocalDeal(userId, notification.product.asin);
          setClaimedMessage(
            `₹${CLAIMED_DEAL_DISCOUNT} discount applied to ${notification.product.name}.`,
          );
        }
      } catch {
        // Ignore; the refresh below reconciles with server state.
      } finally {
        setActionInFlight(false);
        // Refresh notifications after the action (Requirement 8.6).
        void poll();
      }
    },
    [poll, userId],
  );

  const current = notifications[0] ?? null;

  // Nothing to show while no PENDING candidate exists (Requirement 8.3).
  if (current === null) {
    return claimedMessage ? (
      <div
        role="status"
        className="fixed bottom-4 right-4 z-50 w-[min(92vw,22rem)] overflow-hidden rounded-amazon border border-green-700 bg-white shadow-xl"
      >
        <div className="flex items-start gap-3 p-4">
          <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-green-700" />
          <div className="min-w-0">
            <p className="text-sm font-bold text-green-800">Deal claimed</p>
            <p className="mt-1 text-sm text-amazonInk">{claimedMessage}</p>
            <p className="mt-1 text-xs font-medium text-gray-600">
              Checkout now to get this item in 3 hours.
            </p>
          </div>
        </div>
      </div>
    ) : null;
  }

  return (
    <MatchNotificationPopup
      notification={current}
      busy={actionInFlight}
      onClaim={() => void respond(current, "accept")}
      onKeepOriginal={() => void respond(current, "reject")}
    />
  );
}
