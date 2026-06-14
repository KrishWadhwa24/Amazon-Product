"""Resale router — resale listing creation (Requirements 11.2-11.4, 11.6, 11.7).

Wires ``POST /api/resale/list`` to the resale service. The active seller id is
resolved from the signed session cookie via :func:`require_current_user_id`
(Requirement 1.4), which hard-fails anonymous callers with ``401``. The service
validates the condition grade, the mock camera ``condition_image_url``, and the
resale price, then creates an ACTIVE :class:`ResaleListing` (Requirement 11.2).

It also wires the public ``GET /api/resale/feed`` endpoint, which returns the
ACTIVE resale listings (joined with their Product and original purchase date,
newest first) for the verified used-deals feed (Requirements 12.1-12.3, 12.7).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_current_user_id
from app.db.session import get_session
from app.models.enums import ConditionGrade, ResaleStatus
from app.services import resale as resale_service

router = APIRouter(prefix="/api/resale", tags=["resale"])


class CreateListingRequest(BaseModel):
    """Request body for ``POST /api/resale/list`` (Requirement 11.2).

    ``condition_grade`` and ``resale_price`` are typed loosely (``str`` /
    ``Decimal``) so that domain validation — and the precise
    ``UNSUPPORTED_GRADE`` / ``INVALID_RESALE_PRICE`` errors — happens in the
    service rather than as opaque Pydantic 422s. ``condition_image_url`` is
    optional here so the service can raise ``CONDITION_IMAGE_REQUIRED`` when it
    is omitted or empty (Requirement 11.7).
    """

    order_history_id: int
    condition_grade: str
    resale_price: Decimal
    condition_image_url: str | None = None


class ResaleListingResource(BaseModel):
    """Serialized ResaleListing returned to the client."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    order_history_id: int
    seller_id: int
    status: ResaleStatus
    condition_grade: ConditionGrade
    resale_price: Decimal
    condition_image_url: str
    listed_at: datetime


class CreateListingResponse(BaseModel):
    """``201`` response envelope carrying the created ResaleListing.

    ``buyer_total_price`` is ``resale_price + ₹50 Amazon Commission``, the
    final price the buyer will see on the marketplace feed.
    """

    resale_listing: ResaleListingResource
    buyer_total_price: Decimal


class FeedProductResource(BaseModel):
    """Product fields needed by the Split-Trust gallery (Requirement 12.8).

    Carries the official catalog ``image_url`` (the trusted primary image) plus
    ``uploaded_image_path`` so the frontend can prefer an uploaded image when
    present, falling back to ``image_url``/placeholder otherwise.
    """

    model_config = ConfigDict(from_attributes=True)

    asin: str
    name: str
    price: Decimal
    image_url: str
    uploaded_image_path: str | None = None


class ResaleFeedItemResource(BaseModel):
    """A single active resale feed entry (Requirements 12.1, 12.7).

    Includes the listing's own fields, its joined :class:`FeedProductResource`,
    the ``original_purchased_at`` date from the source order, and — for the
    Split-Trust gallery — BOTH the official Product ``image_url`` (nested under
    ``product``) and the listing's ``condition_image_url`` as non-empty URLs.
    ``buyer_total_price`` is ``resale_price + ₹50 Amazon Commission`` — the
    final price shown to buyers on the marketplace.
    """

    id: int
    condition_grade: ConditionGrade
    resale_price: Decimal
    buyer_total_price: Decimal
    status: ResaleStatus
    listed_at: datetime
    condition_image_url: str
    original_purchased_at: datetime
    product: FeedProductResource


@router.post(
    "/list",
    status_code=status.HTTP_201_CREATED,
    response_model=CreateListingResponse,
    summary="Create an ACTIVE resale listing from a previously purchased item",
)
async def create_listing(
    body: CreateListingRequest,
    seller_id: int = Depends(require_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> CreateListingResponse:
    """Create an ACTIVE ResaleListing for the requesting seller.

    Returns ``201`` with the created listing on success. The service raises
    :class:`~app.core.errors.ForbiddenError` (``403``) when the order is not the
    seller's, :class:`~app.core.errors.UnsupportedGradeError`
    (``422 UNSUPPORTED_GRADE``, Requirement 11.4),
    :class:`~app.core.errors.MissingImageError`
    (``422 CONDITION_IMAGE_REQUIRED``, Requirement 11.7), and
    :class:`~app.core.errors.InvalidResalePriceError`
    (``422 INVALID_RESALE_PRICE``, Requirement 11.2); all are rendered as the
    shared error envelope by the application's domain-error handler.
    """
    result = await resale_service.create_listing(
        session,
        seller_id=seller_id,
        order_history_id=body.order_history_id,
        condition_grade=body.condition_grade,
        condition_image_url=body.condition_image_url,
        resale_price=body.resale_price,
    )
    return CreateListingResponse(
        resale_listing=ResaleListingResource.model_validate(result.listing),
        buyer_total_price=result.buyer_total_price,
    )


@router.get(
    "/feed",
    response_model=list[ResaleFeedItemResource],
    summary="List ACTIVE resale listings for the verified used-deals feed",
)
async def get_feed(
    session: AsyncSession = Depends(get_session),
) -> list[ResaleFeedItemResource]:
    """Return all ACTIVE resale listings, newest ``listed_at`` first.

    Each entry is joined with its Product and the original OrderHistory purchase
    date (Requirement 12.1) and carries both the official Product ``image_url``
    and the listing's ``condition_image_url`` as non-empty URLs for the
    Split-Trust gallery (Requirement 12.7). When no ACTIVE listing exists the
    endpoint returns an empty array rather than an error (Requirement 12.2).
    This is a public, unauthenticated read so buyers can browse deals. If the
    Relational_Store is unreachable the service raises
    :class:`~app.core.errors.StoreUnavailableError`, which the domain-error
    handler renders as ``503 STORE_UNAVAILABLE`` with no partial result set
    (Requirement 12.3).
    """
    items = await resale_service.list_active_feed(session)
    return [
        ResaleFeedItemResource(
            id=item.listing.id,
            condition_grade=item.listing.condition_grade,
            resale_price=item.listing.resale_price,
            buyer_total_price=item.buyer_total_price,
            status=item.listing.status,
            listed_at=item.listing.listed_at,
            condition_image_url=item.listing.condition_image_url,
            original_purchased_at=item.original_purchased_at,
            product=FeedProductResource.model_validate(item.listing.product),
        )
        for item in items
    ]


class BuyListingResponse(BaseModel):
    """``200`` response after purchasing a resale listing."""

    id: int
    product_asin: str
    product_name: str
    resale_price: Decimal
    status: ResaleStatus


class CartLineProduct(BaseModel):
    """Product fields surfaced alongside a resale cart line."""

    model_config = ConfigDict(from_attributes=True)

    asin: str
    name: str
    price: Decimal
    image_url: str
    uploaded_image_path: str | None = None


class AddResaleToCartResponse(BaseModel):
    """``201`` response after adding a resale listing to the cart."""

    id: int
    product_id: int
    resale_listing_id: int | None
    unit_price: Decimal | None
    listed_at: datetime
    product: CartLineProduct


@router.post(
    "/{listing_id}/buy",
    response_model=BuyListingResponse,
    summary="Buy an ACTIVE resale listing (marks it SOLD)",
)
async def buy_listing(
    listing_id: int,
    buyer_id: int = Depends(require_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> BuyListingResponse:
    """Purchase an ACTIVE resale listing for the requesting buyer.

    Requires an authenticated session (``401`` otherwise). The service raises
    :class:`~app.core.errors.ResaleListingNotFoundError` (``404``) for an unknown
    id, :class:`~app.core.errors.ResaleListingUnavailableError` (``409``) when
    the listing is no longer ACTIVE, and
    :class:`~app.core.errors.ForbiddenError` (``403``) when the buyer is the
    seller. On success the listing is marked SOLD and removed from the feed.
    """
    listing = await resale_service.buy_listing(
        session, listing_id=listing_id, buyer_id=buyer_id
    )
    return BuyListingResponse(
        id=listing.id,
        product_asin=listing.product.asin,
        product_name=listing.product.name,
        resale_price=listing.resale_price,
        status=listing.status,
    )


@router.post(
    "/{listing_id}/cart",
    status_code=status.HTTP_201_CREATED,
    response_model=AddResaleToCartResponse,
    summary="Add an ACTIVE resale listing to the buyer's cart",
)
async def add_listing_to_cart(
    listing_id: int,
    buyer_id: int = Depends(require_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> AddResaleToCartResponse:
    """Add an ACTIVE resale listing to the requesting buyer's cart.

    Requires an authenticated session (``401`` otherwise). Same 404/409/403
    guards as :func:`buy_listing`. The cart line is created at the discounted
    resale ``unit_price``; the listing stays ACTIVE until it is bought.
    """
    cart_item = await resale_service.add_listing_to_cart(
        session, listing_id=listing_id, buyer_id=buyer_id
    )
    return AddResaleToCartResponse(
        id=cart_item.id,
        product_id=cart_item.product_id,
        resale_listing_id=cart_item.resale_listing_id,
        unit_price=cart_item.unit_price,
        listed_at=cart_item.added_at,
        product=CartLineProduct.model_validate(cart_item.product),
    )
