"""Returns router — return initiation (Requirement 3).

Wires ``POST /api/returns/initiate`` to the return service. The active user id
is resolved from the signed session cookie via :func:`get_current_user_id`
(Requirement 1.4); the service enforces authentication and order-ownership
eligibility (Requirement 3.7) and creates the SCANNING ReturnOrder with its
48-hour window (Requirements 3.1, 3.2).

The lifecycle transition endpoint (task 8.4) and matching (task 10.1) are
intentionally not implemented here.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id, require_current_user_id
from app.db.session import get_session
from app.models.enums import ReturnStatus
from app.models.return_order import ReturnOrder
from app.services import lifecycle
from app.services import returns as returns_service

router = APIRouter(prefix="/api/returns", tags=["returns"])


class InitiateReturnRequest(BaseModel):
    """Request body for ``POST /api/returns/initiate`` (Requirement 3.1)."""

    order_history_id: int


class ReturnOrderResource(BaseModel):
    """Serialized ReturnOrder returned to the client."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    seller_id: int
    product_id: int
    order_history_id: int
    asin: str
    status: ReturnStatus
    initiated_at: datetime
    expires_at: datetime


class InitiateReturnResponse(BaseModel):
    """``201`` response envelope carrying the created ReturnOrder."""

    return_order: ReturnOrderResource


@router.post(
    "/initiate",
    status_code=status.HTTP_201_CREATED,
    response_model=InitiateReturnResponse,
    summary="Initiate a return and enter the 48-hour scanner pool",
)
async def initiate_return(
    body: InitiateReturnRequest,
    user_id: int | None = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> InitiateReturnResponse:
    """Create a SCANNING ReturnOrder for the requesting seller.

    Returns ``201`` with the created return on success. The service raises
    :class:`~app.core.errors.AuthError` (``401``) when there is no session and
    :class:`~app.core.errors.NotEligibleError` (``422``) when the referenced
    order is not in the user's history (Requirement 3.7); both are rendered as
    the shared error envelope by the application's domain-error handler.
    """
    return_order = await returns_service.initiate_return(
        session,
        user_id=user_id,
        order_history_id=body.order_history_id,
    )
    return InitiateReturnResponse(
        return_order=ReturnOrderResource.model_validate(return_order)
    )


class SellerOrderResource(BaseModel):
    """A seller's order joined with its Product plus resale gating."""

    order_history_id: int
    asin: str
    name: str
    price: float
    image_url: str
    uploaded_image_path: str | None
    purchased_at: datetime
    days_since_purchase: int
    resell_eligible: bool
    return_eligible: bool
    return_status: ReturnStatus | None = None
    resale_listing_id: int | None = None
    resale_status: str | None = None


class SellerOrdersResponse(BaseModel):
    """``200`` envelope carrying the authenticated user's order history."""

    orders: list[SellerOrderResource]


@router.get(
    "/orders",
    response_model=SellerOrdersResponse,
    summary="List the authenticated seller's orders with resale eligibility",
)
async def list_orders(
    user_id: int = Depends(require_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> SellerOrdersResponse:
    """Return the active user's OrderHistory joined with each Product.

    Requires an authenticated session (Requirement 1.4); anonymous callers get
    ``401 NO_SESSION`` from :func:`require_current_user_id`. Each order carries a
    computed ``days_since_purchase`` and a ``resell_eligible`` flag set when the
    purchase is more than 7 days old (Requirement 11.1), letting the ``/orders``
    page gate the "Resell via Amazon" action. Returns an empty list (never an
    error) when the user has no orders.
    """
    orders = await returns_service.list_seller_orders(session, user_id=user_id)
    return SellerOrdersResponse(
        orders=[
            SellerOrderResource(
                order_history_id=o.order_history_id,
                asin=o.asin,
                name=o.name,
                price=float(o.price),
                image_url=o.image_url,
                uploaded_image_path=o.uploaded_image_path,
                purchased_at=o.purchased_at,
                days_since_purchase=o.days_since_purchase,
                resell_eligible=o.resell_eligible,
                return_eligible=o.return_eligible,
                return_status=o.return_status,
                resale_listing_id=o.resale_listing_id,
                resale_status=o.resale_status,
            )
            for o in orders
        ]
    )


class TransitionRequest(BaseModel):
    """Request body for ``POST /api/returns/{id}/transition`` (Requirement 10.5)."""

    target_status: ReturnStatus


class TransitionResponse(BaseModel):
    """Confirmation identifying the resulting ReturnOrder status (Req 10.5)."""

    id: int
    status: ReturnStatus


@router.post(
    "/{return_id}/transition",
    response_model=TransitionResponse,
    summary="Transition a ReturnOrder along the lifecycle state machine",
)
async def transition_return(
    return_id: int,
    body: TransitionRequest,
    session: AsyncSession = Depends(get_session),
) -> TransitionResponse:
    """Advance a ReturnOrder to ``target_status`` via the lifecycle core.

    Loads the ReturnOrder, delegates to
    :func:`app.services.lifecycle.transition`, and persists the new status,
    returning ``{id, status}`` on success (Requirement 10.5). An undefined or
    terminal-source transition raises
    :class:`~app.core.errors.InvalidTransitionError`, rendered as
    ``409 INVALID_TRANSITION`` by the domain-error handler with the current
    status left unchanged (Requirement 10.7). An unknown id yields ``404``.
    """
    return_order = await session.get(ReturnOrder, return_id)
    if return_order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ReturnOrder {return_id} not found",
        )

    # Delegate to the pure state machine; raises InvalidTransitionError (409)
    # without mutating anything when the (source, target) pair is undefined.
    new_status = lifecycle.transition(return_order.status, body.target_status)
    return_order.status = new_status
    await session.commit()

    return TransitionResponse(id=return_order.id, status=new_status)
