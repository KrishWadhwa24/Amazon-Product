"""Notification service — buyer-facing PENDING deal feed (Requirements 7, 8).

Surfaces the active Buyer's PENDING :class:`~app.models.match_candidate.MatchCandidate`
records as enriched "Local Open-Box Deal" notifications. Each candidate is
joined to its :class:`~app.models.return_order.ReturnOrder` and the returned
:class:`~app.models.product.Product` so the popup can render the deal headline,
the money/time/carbon saved, the distance, and the product display fields
(Requirements 8.1, 8.2).

Preservation semantics (Requirement 8.6): a notification stays PENDING until it
is delivered or its ReturnOrder leaves SCANNING. We therefore only surface
candidates whose ReturnOrder is *still* SCANNING — once the return advances
(e.g. the buyer accepted, or it expired) the deal is no longer offered. Serving
a candidate stamps ``delivered_at`` on its PENDING Notification row without
changing the candidate's status (the accept/reject flow owns that transition).

Carbon suppression (Requirement 7.3): when the carbon avoided for a candidate is
below 0.1 kg, the carbon field is omitted entirely so the UI makes no
environmental claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import MatchStatus, NotificationStatus, ReturnStatus
from app.models.match_candidate import MatchCandidate
from app.models.notification import Notification
from app.models.product import Product
from app.models.return_order import ReturnOrder

# The fixed headline for a discovered local open-box deal (Requirement 8.3 /
# demo scenario): "🔥 Local Open-Box Deal Found Near You".
DEAL_HEADLINE = "🔥 Local Open-Box Deal Found Near You"

# Carbon avoided below this threshold (kg CO2) is suppressed (Requirement 7.3).
CARBON_SUPPRESSION_THRESHOLD_KG = 0.1


@dataclass(frozen=True)
class NotificationView:
    """Enriched, display-ready view of one PENDING deal notification.

    ``carbon_avoided_kg`` is ``None`` when the avoided carbon is below the
    suppression threshold (Requirement 7.3) so the transport layer omits it and
    the UI makes no environmental claim.
    """

    candidate_id: int
    headline: str
    money_saved: Decimal
    delivery_time_saved_hours: int
    distance_km: float
    product_name: str
    product_asin: str
    product_image_url: str
    product_uploaded_image_path: str | None = None
    carbon_avoided_kg: float | None = None


def _carbon_for_display(carbon_avoided_kg: float) -> float | None:
    """Return the rounded carbon value, or ``None`` when it must be suppressed.

    Per Requirement 7.3 a candidate whose avoided carbon is below 0.1 kg CO2 is
    delivered without any environmental claim, so the value is omitted. Otherwise
    it is rounded to 1 decimal place (Requirement 7.2).
    """
    if carbon_avoided_kg < CARBON_SUPPRESSION_THRESHOLD_KG:
        return None
    return round(carbon_avoided_kg, 1)


async def list_pending_for_buyer(
    session: AsyncSession,
    buyer_id: int,
    *,
    now: datetime | None = None,
) -> list[NotificationView]:
    """Return the active Buyer's PENDING deals enriched for display.

    Selects every PENDING MatchCandidate owned by ``buyer_id`` whose ReturnOrder
    is still SCANNING (Requirement 8.6), joined to its Product, and maps each to
    a :class:`NotificationView` with the deal headline, money/time/carbon saved,
    distance, and product display fields (Requirements 8.1, 8.2). Carbon is
    omitted when below the suppression threshold (Requirement 7.3).

    As a side effect, each served candidate's PENDING Notification row is stamped
    ``delivered_at`` (status left unchanged) so delivery is recorded without
    retiring the offer; the accept/reject flow owns the candidate transition.

    Args:
        session: The active async DB session (the unit of transaction).
        buyer_id: The active Buyer's id, resolved from the session cookie.
        now: Optional delivery timestamp (defaults to ``datetime.now(UTC)``);
            injectable for deterministic tests.

    Returns:
        A list of :class:`NotificationView`, one per surfaced PENDING deal.
    """
    stmt = (
        select(MatchCandidate, Product)
        .join(ReturnOrder, MatchCandidate.return_order_id == ReturnOrder.id)
        .join(Product, ReturnOrder.product_id == Product.id)
        .where(
            MatchCandidate.buyer_id == buyer_id,
            MatchCandidate.status == MatchStatus.PENDING,
            ReturnOrder.status == ReturnStatus.SCANNING,
        )
        .order_by(MatchCandidate.created_at.desc(), MatchCandidate.id.desc())
    )
    rows = (await session.execute(stmt)).all()

    views: list[NotificationView] = []
    served_ids: list[int] = []
    for candidate, product in rows:
        served_ids.append(candidate.id)
        views.append(
            NotificationView(
                candidate_id=candidate.id,
                headline=DEAL_HEADLINE,
                money_saved=candidate.local_discount,
                delivery_time_saved_hours=candidate.delivery_time_saved_hours,
                distance_km=candidate.distance_km,
                product_name=product.name,
                product_asin=product.asin,
                product_image_url=product.image_url,
                product_uploaded_image_path=product.uploaded_image_path,
                carbon_avoided_kg=_carbon_for_display(candidate.carbon_avoided_kg),
            )
        )

    if served_ids:
        delivered_at = now or datetime.now(timezone.utc)
        # Record delivery on the PENDING Notification rows without changing their
        # status: Requirement 8.6 keeps them PENDING until accepted/rejected or
        # the ReturnOrder leaves SCANNING.
        await session.execute(
            update(Notification)
            .where(
                Notification.match_candidate_id.in_(served_ids),
                Notification.status == NotificationStatus.PENDING,
                Notification.delivered_at.is_(None),
            )
            .values(delivered_at=delivered_at)
            .execution_options(synchronize_session=False)
        )
        await session.commit()

    return views
