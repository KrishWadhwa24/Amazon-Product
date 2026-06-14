"""Match candidate lifecycle service — accept/reject + cascade (Requirement 9).

Owns the buyer-facing transitions of a :class:`~app.models.match_candidate.MatchCandidate`
and the side effects that ripple out from accepting a local open-box deal:

* ``accept`` sets the candidate ACCEPTED (Requirement 9.2), advances its
  ReturnOrder along the local-delivery path
  ``SCANNING -> MATCH_FOUND -> BUYER_ACCEPTED -> LOCAL_DELIVERY`` via the pure
  lifecycle core (Requirement 9.5), and EXPIRES every other PENDING sibling
  candidate for the same ReturnOrder (Requirements 9.4, 9.8).
* ``reject`` sets the candidate REJECTED (Requirement 9.3).

Both actions enforce the same guards first:

* ownership — the acting user must be the candidate's buyer, else
  :class:`~app.core.errors.ForbiddenError` (``403 NOT_AUTHORIZED``, Requirement 9.7);
* PENDING-only — the candidate must still be PENDING, else
  :class:`~app.core.errors.OfferUnavailableError` (``409 OFFER_UNAVAILABLE``,
  Requirement 9.6).

A rejected guard leaves the candidate (and its ReturnOrder) unchanged. The
transport layer (``app.api.matches``) loads the candidate, resolves the active
user from the session cookie, and maps these domain errors to the shared error
envelope.

Feature 3 — Zero-Mile Logistics Savings
----------------------------------------
When a match is accepted the return bypasses the main FC and is delivered
locally, saving reverse-logistics cost. ``accept_match`` records 10% of the
product's original price in the ``logistics_savings_paise`` AnalyticsCounter
(integer paise = ₹ × 100) so the Admin dashboard can show a cumulative,
event-driven "Logistics Savings (Zero-Mile)" metric that persists correctly
across sessions and never depends on a fragile live status join.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ForbiddenError, OfferUnavailableError
from app.models.analytics_counter import AnalyticsCounter
from app.models.enums import MatchStatus, ReturnStatus
from app.models.match_candidate import MatchCandidate
from app.models.return_order import ReturnOrder
from app.services import lifecycle

#: AnalyticsCounter name for cumulative logistics savings stored in paise (₹×100).
LOGISTICS_SAVINGS_COUNTER: str = "logistics_savings_paise"

#: Fraction of the product's original price saved per zero-mile local delivery.
LOGISTICS_SAVINGS_RATE: Decimal = Decimal("0.10")

# The exact local-delivery advancement path taken when a candidate is accepted
# (Requirement 9.5). Each hop is validated by the pure lifecycle state machine.
ACCEPT_RETURN_PATH: tuple[ReturnStatus, ...] = (
    ReturnStatus.MATCH_FOUND,
    ReturnStatus.BUYER_ACCEPTED,
    ReturnStatus.LOCAL_DELIVERY,
)


def _authorize(candidate: MatchCandidate, user_id: int | None) -> None:
    """Raise :class:`ForbiddenError` unless ``user_id`` owns the candidate.

    Per Requirement 9.7 a user whose identifier does not match the candidate's
    buyer may not accept or reject it; the action is rejected with
    ``403 NOT_AUTHORIZED`` and nothing is mutated.
    """
    if user_id is None or candidate.buyer_id != user_id:
        raise ForbiddenError()


def _ensure_pending(candidate: MatchCandidate) -> None:
    """Raise :class:`OfferUnavailableError` unless the candidate is PENDING.

    Per Requirement 9.6 accepting or rejecting a candidate that is not PENDING
    is rejected with ``409 OFFER_UNAVAILABLE`` and leaves the status unchanged.
    """
    if candidate.status != MatchStatus.PENDING:
        raise OfferUnavailableError()


async def _expire_sibling_pending(
    session: AsyncSession, *, return_order_id: int, except_id: int
) -> None:
    """Set every OTHER PENDING candidate for the return to EXPIRED (Req 9.8).

    A bulk UPDATE flips all PENDING candidates for ``return_order_id`` other
    than ``except_id`` to EXPIRED. This also satisfies Requirement 9.4 for the
    accept path: when the ReturnOrder leaves SCANNING, no PENDING sibling
    candidate is left outstanding.
    """
    await session.execute(
        update(MatchCandidate)
        .where(
            MatchCandidate.return_order_id == return_order_id,
            MatchCandidate.id != except_id,
            MatchCandidate.status == MatchStatus.PENDING,
        )
        .values(status=MatchStatus.EXPIRED)
        .execution_options(synchronize_session=False)
    )


async def accept_match(
    session: AsyncSession,
    candidate: MatchCandidate,
    *,
    user_id: int | None,
) -> MatchCandidate:
    """Accept a PENDING MatchCandidate and advance its ReturnOrder (Req 9.2, 9.5, 9.8).

    Enforces ownership (Requirement 9.7) and PENDING-only (Requirement 9.6)
    guards first — either raises without mutation. On success, within one
    committed transaction it:

    1. Sets the candidate ACCEPTED.
    2. Advances the ReturnOrder ``SCANNING -> MATCH_FOUND -> BUYER_ACCEPTED ->
       LOCAL_DELIVERY`` through the pure lifecycle core (Requirement 9.5).
    3. EXPIRES every other PENDING candidate for the same ReturnOrder
       (Requirements 9.4, 9.8).
    4. Records 10% of the product's original price in the
       ``logistics_savings_paise`` AnalyticsCounter (Feature 3) so the Admin
       dashboard's "Logistics Savings (Zero-Mile)" KPI accumulates correctly.

    Args:
        session: The active async DB session (the unit of transaction).
        candidate: The MatchCandidate to accept, with its ``return_order``
            relationship loaded.
        user_id: The acting user's id resolved from the session cookie.

    Returns:
        The accepted :class:`MatchCandidate` (status ACCEPTED).
    """
    _authorize(candidate, user_id)
    _ensure_pending(candidate)

    candidate.status = MatchStatus.ACCEPTED  # Requirement 9.2

    # Advance the associated ReturnOrder along the local-delivery path. Each hop
    # is validated by the lifecycle state machine (Requirement 9.5); a PENDING
    # candidate implies a SCANNING return, so the full path is legal.
    return_order: ReturnOrder = candidate.return_order
    for target in ACCEPT_RETURN_PATH:
        return_order.status = lifecycle.transition(return_order.status, target)

    # Expire all other outstanding PENDING candidates for this return
    # (Requirements 9.4, 9.8).
    await _expire_sibling_pending(
        session, return_order_id=return_order.id, except_id=candidate.id
    )

    # --- Feature 3: Record logistics savings (10% of product price) ---
    # Load the product for this return to read its price.
    # We use a targeted query rather than an extra eager-load on the caller so
    # the API layer doesn't need changing.
    return_order_with_product = (
        await session.execute(
            select(ReturnOrder)
            .where(ReturnOrder.id == return_order.id)
            .options(selectinload(ReturnOrder.product))
        )
    ).scalar_one_or_none()

    if return_order_with_product is not None and return_order_with_product.product is not None:
        product_price = Decimal(str(return_order_with_product.product.price))
        savings = (product_price * LOGISTICS_SAVINGS_RATE).to_integral_value()
        savings_paise = int(savings)  # already in rupees — store as paise (×100)
        savings_paise_full = int((product_price * LOGISTICS_SAVINGS_RATE * 100).to_integral_value())

        savings_counter = (
            await session.execute(
                select(AnalyticsCounter).where(
                    AnalyticsCounter.name == LOGISTICS_SAVINGS_COUNTER
                )
            )
        ).scalar_one_or_none()

        if savings_counter is None:
            session.add(
                AnalyticsCounter(name=LOGISTICS_SAVINGS_COUNTER, value=savings_paise_full)
            )
        else:
            savings_counter.value = savings_counter.value + savings_paise_full

    await session.commit()
    await session.refresh(candidate)
    return candidate


async def reject_match(
    session: AsyncSession,
    candidate: MatchCandidate,
    *,
    user_id: int | None,
) -> MatchCandidate:
    """Reject a PENDING MatchCandidate (Requirement 9.3).

    Enforces the same ownership (Requirement 9.7) and PENDING-only
    (Requirement 9.6) guards as :func:`accept_match`. On success sets the
    candidate REJECTED and commits; the ReturnOrder and sibling candidates are
    left untouched (rejecting one buyer's offer does not retire the return).

    Args:
        session: The active async DB session.
        candidate: The MatchCandidate to reject.
        user_id: The acting user's id resolved from the session cookie.

    Returns:
        The rejected :class:`MatchCandidate` (status REJECTED).
    """
    _authorize(candidate, user_id)
    _ensure_pending(candidate)

    candidate.status = MatchStatus.REJECTED  # Requirement 9.3
    await session.commit()
    await session.refresh(candidate)
    return candidate
