"""Notifications router — buyer-facing PENDING deal feed (Requirements 7, 8).

Wires ``GET /api/notifications`` to :mod:`app.services.notifications`. The active
Buyer is resolved from the signed session cookie (Requirement 1.4) and required
(anonymous callers get ``401 NO_SESSION``). The endpoint returns the buyer's
PENDING MatchCandidates whose ReturnOrder is still SCANNING (Requirement 8.6),
each enriched with the deal headline, money/time saved, distance, and product
display fields (Requirements 8.1, 8.2). Carbon avoided is omitted when below the
suppression threshold (Requirement 7.3).
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_current_user_id
from app.db.session import get_session
from app.services import notifications as notifications_service

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class NotificationProductItem(BaseModel):
    """The matched product, nested under a notification (Requirement 8.2).

    Mirrors the frontend ``NotificationProduct`` shape so the popup can render
    the product image (preferring an uploaded photo) and name directly.
    """

    name: str
    asin: str
    image_url: str
    uploaded_image_path: str | None = None


class NotificationItem(BaseModel):
    """A single enriched PENDING deal notification (Requirements 7, 8).

    ``carbon_avoided_kg`` is omitted from the serialized payload when ``None``
    (carbon suppression, Requirement 7.3) so the UI makes no environmental claim.
    The matched product is nested under ``product`` to match the buyer-facing
    popup's contract.
    """

    candidate_id: int
    headline: str
    money_saved: Decimal
    delivery_time_saved_hours: int
    distance_km: float
    product: NotificationProductItem
    carbon_avoided_kg: float | None = None

    model_config = {"json_schema_extra": {"examples": []}}


@router.get(
    "",
    response_model=list[NotificationItem],
    response_model_exclude_none=True,
    summary="List PENDING local open-box deals for the active buyer",
)
async def list_notifications(
    user_id: int = Depends(require_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> list[NotificationItem]:
    """Return the active Buyer's PENDING deal notifications (Requirements 8.1, 8.6).

    Requires an authenticated buyer (``401 NO_SESSION`` otherwise). Each item
    carries the deal headline, money saved, delivery time saved, distance, and
    product display fields; carbon avoided is included only when at or above the
    suppression threshold (Requirement 7.3). ``response_model_exclude_none``
    drops the carbon field entirely when suppressed.
    """
    views = await notifications_service.list_pending_for_buyer(session, user_id)
    return [
        NotificationItem(
            candidate_id=view.candidate_id,
            headline=view.headline,
            money_saved=view.money_saved,
            delivery_time_saved_hours=view.delivery_time_saved_hours,
            distance_km=view.distance_km,
            product=NotificationProductItem(
                name=view.product_name,
                asin=view.product_asin,
                image_url=view.product_image_url,
                uploaded_image_path=view.product_uploaded_image_path,
            ),
            carbon_avoided_kg=view.carbon_avoided_kg,
        )
        for view in views
    ]
