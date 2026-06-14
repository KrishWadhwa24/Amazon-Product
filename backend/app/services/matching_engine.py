"""Matching Engine I/O shell + demand→match orchestration (Requirement 6).

The pure selection logic lives in :mod:`app.core.matching`
(``select_match``/``haversine_km``). This module is its **I/O shell**: it loads
candidate ReturnOrders from PostgreSQL, adapts them into the pure core's value
objects, runs the selection, and — when a candidate qualifies — persists a
PENDING MatchCandidate with its cached deal impact, bumps the active-match
counter, and enqueues a notification. All of that happens inside a single
transaction (Requirements 6.1, 6.5, 6.6, 6.7, 6.9, 6.10, 9.1).

Pipeline (design "Matching Engine" / Flow 18):

1. Build the :class:`~app.core.matching.Buyer` from the signal's ASIN and the
   buyer's coordinates (Requirement 6.1).
2. Query candidate ReturnOrders — ``status = SCANNING``, ``expires_at > now``,
   matching ASIN, ``seller_id != buyer_id`` — joined to their seller's
   coordinates and their product, and adapt each to a
   :class:`~app.core.matching.Candidate` (Requirement 6.2).
3. Run :func:`~app.core.matching.select_match` to pick the nearest eligible
   candidate within the 20 km Match_Radius, earliest ``expires_at`` breaking
   ties (Requirements 6.3, 6.4, 6.8).
4. If nothing qualifies, create nothing and leave existing candidates unchanged
   (Requirement 6.10).
5. Duplicate guard: skip when a PENDING MatchCandidate already exists for the
   ``(return_order, buyer)`` pair (Requirement 6.9).
6. Otherwise create one PENDING MatchCandidate (Requirements 6.5, 9.1) carrying
   ``distance_km``, ``signal_source``, and the cached deal impact from the
   pricing core (Requirement 7); increment the active-match count
   (Requirement 6.7); and enqueue a Notification row the notifications endpoint
   will deliver (Requirement 6.6). Commit once.

The companion orchestrator :func:`record_and_match` chains
:func:`app.services.demand.record_signal` (the Redis write) with
:func:`run_matching_for_signal` so a successful demand-signal recording triggers
matching, without changing ``record_signal``'s own signature.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.matching import Buyer, Candidate, Point, select_match
from app.db.redis_gateway import RedisGateway
from app.models.enums import MatchStatus, NotificationStatus, ReturnStatus
from app.models.match_candidate import MatchCandidate
from app.models.notification import Notification
from app.models.return_order import ReturnOrder
from app.services.analytics import increment_active_match_count
from app.services.demand import SignalResult, record_signal
from app.services.pricing import estimate_logistics, savings_summary


def _utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


async def _load_candidate_returns(
    session: AsyncSession,
    *,
    asin: str,
    buyer_id: int,
    now: datetime,
) -> list[ReturnOrder]:
    """Load SCANNING, non-expired ReturnOrders for ``asin`` from another seller.

    Implements the Requirement 6.2 candidate query: status SCANNING, window
    still open (``expires_at > now``), matching ASIN, and a seller different
    from the buyer. The seller (for coordinates) and product (for pricing) are
    eagerly loaded so the shell can build the pure value objects and compute the
    deal impact without extra round-trips.
    """
    stmt = (
        select(ReturnOrder)
        .where(
            and_(
                ReturnOrder.status == ReturnStatus.SCANNING,
                ReturnOrder.expires_at > now,
                ReturnOrder.asin == asin,
                ReturnOrder.seller_id != buyer_id,
            )
        )
        .options(
            selectinload(ReturnOrder.seller),
            selectinload(ReturnOrder.product),
        )
    )
    return list((await session.execute(stmt)).scalars().all())


async def _pending_exists(
    session: AsyncSession, *, return_order_id: int, buyer_id: int
) -> bool:
    """Return True when a PENDING MatchCandidate exists for the pair (Req 6.9)."""
    stmt = select(MatchCandidate.id).where(
        MatchCandidate.return_order_id == return_order_id,
        MatchCandidate.buyer_id == buyer_id,
        MatchCandidate.status == MatchStatus.PENDING,
    )
    return (await session.execute(stmt)).first() is not None


async def run_matching_for_signal(
    session: AsyncSession,
    *,
    asin: str,
    buyer_id: int,
    signal_source: str,
    buyer_lat: float,
    buyer_lon: float,
    now: Optional[datetime] = None,
) -> Optional[MatchCandidate]:
    """Run the matching engine for one recorded demand signal (Requirement 6).

    Loads candidate ReturnOrders for ``asin``, selects the nearest eligible one
    within the Match_Radius via the pure core, and — unless a PENDING candidate
    already exists for the pair — creates a PENDING :class:`MatchCandidate` with
    its cached deal impact, increments the active-match count, and enqueues a
    notification, all in a single committed transaction. Returns the created
    MatchCandidate, or ``None`` when nothing qualifies or a duplicate is guarded
    (Requirements 6.5, 6.6, 6.7, 6.9, 6.10, 9.1).

    Args:
        session: The active async DB session (the unit of transaction).
        asin: The ASIN the demand signal targets (Requirement 6.1).
        buyer_id: The buyer that produced the signal (self-match excluded).
        signal_source: One of ``cart``/``buynow``/``wishlist``/``viewed``;
            stored on the created candidate (Requirement 6.5).
        buyer_lat: Buyer latitude in ``[-90, 90]``.
        buyer_lon: Buyer longitude in ``[-180, 180]``.
        now: Reference "current time" for the non-expired check; defaults to the
            current UTC time. Injectable for deterministic tests.
    """
    moment = now or _utcnow()

    buyer = Buyer(
        id=buyer_id,
        point=Point(lat=buyer_lat, lon=buyer_lon),
        asin=asin,
        now=moment,
    )

    returns = await _load_candidate_returns(
        session, asin=asin, buyer_id=buyer_id, now=moment
    )
    if not returns:
        # No candidate ReturnOrder satisfies the conditions (Requirement 6.10).
        return None

    # Adapt rows to pure value objects, keeping a lookup back to the row so we
    # can read the product price for the selected candidate's deal impact.
    by_id: dict[int, ReturnOrder] = {r.id: r for r in returns}
    candidates = [
        Candidate(
            return_order_id=r.id,
            seller_id=r.seller_id,
            seller_point=Point(lat=r.seller.latitude, lon=r.seller.longitude),
            asin=r.asin,
            status=r.status,
            expires_at=r.expires_at,
        )
        for r in returns
    ]

    selection = select_match(candidates, buyer)
    if selection is None:
        # Nothing within the Match_Radius — create nothing (Requirements 6.8, 6.10).
        return None

    return_order = by_id[selection.candidate.return_order_id]

    # Duplicate guard: an existing PENDING candidate for this pair means we do
    # nothing (Requirement 6.9).
    if await _pending_exists(
        session, return_order_id=return_order.id, buyer_id=buyer_id
    ):
        return None

    # Cache the deal impact from the pricing core (Requirement 7). The
    # estimation inputs are the mocked logistics seam; the clamp/rounding is real.
    product_price = return_order.product.price
    est_savings, delivery_hours, carbon_kg = estimate_logistics(
        product_price, selection.distance_km
    )
    summary = savings_summary(
        product_price, est_savings, delivery_hours, carbon_kg
    )

    candidate = MatchCandidate(
        return_order_id=return_order.id,
        buyer_id=buyer_id,
        status=MatchStatus.PENDING,  # Requirement 9.1
        distance_km=selection.distance_km,
        signal_source=signal_source,
        local_discount=summary.money_saved,
        delivery_time_saved_hours=summary.delivery_time_saved_hours,
        carbon_avoided_kg=summary.carbon_avoided_kg,
        created_at=moment,
    )
    session.add(candidate)
    await session.flush()  # assign candidate.id for the notification FK

    # Increment the active-match count (Requirement 6.7).
    await increment_active_match_count(session)

    # Enqueue the match notification (Requirement 6.6). The PENDING Notification
    # row is what the notifications endpoint (task 21.1) delivers to the buyer.
    notification = Notification(
        match_candidate_id=candidate.id,
        buyer_id=buyer_id,
        status=NotificationStatus.PENDING,
        created_at=moment,
    )
    session.add(notification)

    # One transaction for the whole match-creation flow.
    await session.commit()
    await session.refresh(candidate)
    return candidate


async def record_and_match(
    session: AsyncSession,
    intent: str,
    asin: str,
    buyer_id: int,
    lon: float,
    lat: float,
    *,
    gateway: Optional[RedisGateway] = None,
    recorded_at_ms: Optional[int] = None,
    now: Optional[datetime] = None,
) -> tuple[SignalResult, Optional[MatchCandidate]]:
    """Record a demand signal, then run matching for it (Requirements 4 → 6).

    Service-level orchestration that a successful demand-signal recording
    triggers matching (the HTTP endpoints are wired in task 20.2). It first
    calls :func:`app.services.demand.record_signal` (the validated Redis write);
    only if that succeeds does it invoke :func:`run_matching_for_signal`, so a
    rejected or failed signal never produces a match. ``record_signal``'s own
    signature is unchanged.

    Args:
        session: The active async DB session used for matching.
        intent: The demand intent / signal source (``cart``/``buynow``/
            ``wishlist``/``viewed``).
        asin: The product ASIN the buyer signalled intent for.
        buyer_id: The buyer identifier.
        lon: Buyer longitude in ``[-180, 180]``.
        lat: Buyer latitude in ``[-90, 90]``.
        gateway: Optional Redis gateway override (forwarded to ``record_signal``).
        recorded_at_ms: Optional epoch-ms override (forwarded to ``record_signal``).
        now: Optional reference time for the matching non-expired check.

    Returns:
        A ``(SignalResult, MatchCandidate | None)`` tuple: the recorded signal
        and the created match (``None`` when no candidate qualified).
    """
    result = await record_signal(
        intent,
        asin,
        buyer_id,
        lon,
        lat,
        gateway=gateway,
        recorded_at_ms=recorded_at_ms,
    )
    match = await run_matching_for_signal(
        session,
        asin=asin,
        buyer_id=int(buyer_id),
        signal_source=intent,
        buyer_lat=lat,
        buyer_lon=lon,
        now=now,
    )
    return result, match
