"""Resale service — listing creation (Requirements 11.2-11.4, 11.6, 11.7).

Owns the side-effecting parts of resale *listing creation*. The mock AI camera
grading result (``condition_grade``) and the captured ``condition_image_url``
are produced by the frontend's mock scan (Requirement 11.5) and supplied to
:func:`create_listing`, which validates them and persists an ACTIVE
:class:`ResaleListing`.

A flat ₹50 **Amazon Commission** is added on top of every resale listing's
``resale_price``. The ``resale_price`` column stores the seller's base price
(validated ``0 < base_price <= product.price``); the buyer-facing total
``base_price + RESALE_COMMISSION`` is returned in the API response alongside
the base price so frontends can show the breakdown. The commission is also
accumulated into the admin profit tracker via ``GET /api/admin/metrics``.

Validation rules (all reject without creating a listing):

* The referenced :class:`OrderHistory` must exist **and belong to the requesting
  seller**, else :class:`ForbiddenError` (ownership/eligibility).
* ``condition_grade`` must be one of "Like New", "Good", or "Fair"
  (Requirements 11.3, 11.4), else :class:`UnsupportedGradeError`.
* ``condition_image_url`` must be a non-empty (non-whitespace) string
  (Requirements 11.6, 11.7), else :class:`MissingImageError`.
* ``resale_price`` must satisfy ``0 < resale_price <= product.price``
  (Requirement 11.2), else :class:`InvalidResalePriceError`.

On success the ResaleListing is created with ``status=ACTIVE``, the provided
grade/image, and ``listed_at`` set to the current server time (Requirement
11.2). ``now`` is injectable for deterministic testing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import (
    ForbiddenError,
    InvalidResalePriceError,
    MissingImageError,
    ResaleListingNotFoundError,
    ResaleListingUnavailableError,
    StoreUnavailableError,
    UnsupportedGradeError,
)
from app.models.cart_item import CartItem
from app.models.enums import ConditionGrade
from app.models.order_history import OrderHistory
from app.models.resale_listing import ResaleListing
from app.models.enums import ResaleStatus

#: Flat Amazon commission added to every resale listing price (₹50).
RESALE_COMMISSION: Decimal = Decimal("50.00")


@dataclass(frozen=True)
class ResaleFeedItem:
    """A single resale feed row: an ACTIVE listing + its source purchase date.

    ``listing`` carries its eagerly-loaded :class:`~app.models.product.Product`
    (via ``listing.product``) so the transport layer can shape both the official
    Product ``image_url`` and the listing's ``condition_image_url`` without an
    extra query (Requirement 12.7). ``original_purchased_at`` is the
    ``purchased_at`` of the originating :class:`OrderHistory` (Requirement 12.1).
    ``buyer_total_price`` is ``listing.resale_price + RESALE_COMMISSION`` — the
    final price shown to the buyer.
    """

    listing: ResaleListing
    original_purchased_at: datetime

    @property
    def buyer_total_price(self) -> Decimal:
        """Return the buyer-facing price: base resale price + ₹50 commission."""
        return self.listing.resale_price + RESALE_COMMISSION


def _utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def _coerce_condition_grade(condition_grade: object) -> ConditionGrade:
    """Return the :class:`ConditionGrade` for ``condition_grade`` or raise.

    Accepts an already-constructed :class:`ConditionGrade` or one of the exact
    string values "Like New", "Good", "Fair" (Requirement 11.3). Any other
    value (including casing/whitespace variants and ``None``) raises
    :class:`UnsupportedGradeError` (Requirement 11.4).
    """
    if isinstance(condition_grade, ConditionGrade):
        return condition_grade
    try:
        return ConditionGrade(condition_grade)
    except ValueError as exc:  # not one of the accepted values
        raise UnsupportedGradeError(condition_grade) from exc


def _coerce_resale_price(resale_price: object, product_price: Decimal) -> Decimal:
    """Return a validated :class:`Decimal` resale price or raise.

    Enforces ``0 < resale_price <= product_price`` (Requirement 11.2); rejects
    non-numeric, ``None``, non-positive, and over-ceiling values with
    :class:`InvalidResalePriceError`.
    """
    try:
        price = Decimal(str(resale_price))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvalidResalePriceError(resale_price, product_price) from exc
    if price <= 0 or price > product_price:
        raise InvalidResalePriceError(price, product_price)
    return price


@dataclass(frozen=True)
class CreateListingResult:
    """Outcome of :func:`create_listing`.

    ``listing`` is the persisted :class:`ResaleListing`.
    ``buyer_total_price`` is ``listing.resale_price + RESALE_COMMISSION`` — the
    final price shown to the buyer including the ₹50 Amazon Commission.
    """

    listing: ResaleListing
    buyer_total_price: Decimal


async def create_listing(
    session: AsyncSession,
    *,
    seller_id: int,
    order_history_id: int,
    condition_grade: object,
    condition_image_url: object,
    resale_price: object,
    now: datetime | None = None,
) -> CreateListingResult:
    """Create an ACTIVE ResaleListing for ``order_history_id`` (Requirement 11).

    See the module docstring for the full validation contract. Returns a
    :class:`CreateListingResult` on success carrying the persisted listing and
    the buyer-facing total price (``resale_price + ₹50 commission``).
    """
    moment = now or _utcnow()

    # 1) condition_image_url must be a non-empty string (Req 11.6, 11.7).
    if not isinstance(condition_image_url, str) or not condition_image_url.strip():
        raise MissingImageError()

    # 2) condition_grade must be one of the accepted values (Req 11.3, 11.4).
    grade = _coerce_condition_grade(condition_grade)

    # 3) Ownership: the source purchase must belong to the requesting seller.
    stmt = (
        select(OrderHistory)
        .where(OrderHistory.id == order_history_id)
        .options(selectinload(OrderHistory.product))
    )
    order_history = (await session.execute(stmt)).scalar_one_or_none()
    if order_history is None or order_history.user_id != seller_id:
        raise ForbiddenError(
            "You are not authorized to resell an order that is not in your "
            "purchase history."
        )

    product = order_history.product

    # 4) 0 < resale_price <= product.price (Req 11.2) — reject if invalid.
    price = _coerce_resale_price(resale_price, product.price)

    listing = ResaleListing(
        product_id=product.id,
        order_history_id=order_history.id,
        seller_id=seller_id,
        status=ResaleStatus.ACTIVE,
        condition_grade=grade,
        resale_price=price,
        condition_image_url=condition_image_url,
        listed_at=moment,
    )
    session.add(listing)
    await session.commit()
    await session.refresh(listing)
    return CreateListingResult(
        listing=listing,
        buyer_total_price=(price + RESALE_COMMISSION).quantize(Decimal("0.01")),
    )


async def list_active_feed(session: AsyncSession) -> list[ResaleFeedItem]:
    """Return the active resale marketplace feed (Requirements 12.1-12.3, 12.7).

    Selects every :class:`ResaleListing` with ``status == ACTIVE``, joined with
    its source :class:`OrderHistory` to surface the original ``purchased_at``
    date, ordered by ``listed_at`` descending so the most recently listed item
    is first (Requirement 12.1). Each listing's :class:`~app.models.product.\
    Product` is eagerly loaded so the caller can render both the official
    Product ``image_url`` and the listing's ``condition_image_url``
    (Requirement 12.7).

    When no ACTIVE listing exists this returns an empty list rather than raising
    (Requirement 12.2). If the Relational_Store cannot be reached, the
    underlying :class:`SQLAlchemyError` is converted into a
    :class:`StoreUnavailableError` (mapped to ``503 STORE_UNAVAILABLE``) and the
    full result set is materialized before returning, so a partial set is never
    surfaced (Requirement 12.3).
    """
    stmt = (
        select(ResaleListing, OrderHistory.purchased_at)
        .join(OrderHistory, ResaleListing.order_history_id == OrderHistory.id)
        .where(ResaleListing.status == ResaleStatus.ACTIVE)
        .order_by(ResaleListing.listed_at.desc())
        .options(selectinload(ResaleListing.product))
    )
    try:
        result = await session.execute(stmt)
        # Materialize the entire result set inside the guarded block so a store
        # failure mid-iteration cannot yield a partial feed (Requirement 12.3).
        rows = result.all()
    except SQLAlchemyError as exc:  # store unreachable / query failure
        raise StoreUnavailableError() from exc

    return [
        ResaleFeedItem(listing=listing, original_purchased_at=purchased_at)
        for listing, purchased_at in rows
    ]


async def _load_active_listing(
    session: AsyncSession, listing_id: int
) -> ResaleListing:
    """Load an ACTIVE :class:`ResaleListing` with its product, or raise.

    Raises :class:`ResaleListingNotFoundError` (404) when the id is unknown and
    :class:`ResaleListingUnavailableError` (409) when the listing is no longer
    ACTIVE (already SOLD or REMOVED).
    """
    stmt = (
        select(ResaleListing)
        .where(ResaleListing.id == listing_id)
        .options(selectinload(ResaleListing.product))
    )
    listing = (await session.execute(stmt)).scalar_one_or_none()
    if listing is None:
        raise ResaleListingNotFoundError(listing_id)
    if listing.status != ResaleStatus.ACTIVE:
        raise ResaleListingUnavailableError()
    return listing


async def buy_listing(
    session: AsyncSession,
    *,
    listing_id: int,
    buyer_id: int,
) -> ResaleListing:
    """Purchase an ACTIVE resale listing, marking it SOLD.

    Loads the ACTIVE listing (404/409 otherwise), rejects a seller buying their
    own listing with :class:`ForbiddenError` (403), then sets the listing's
    status to SOLD and commits so it leaves the marketplace feed. Returns the
    sold listing (with its product loaded).
    """
    listing = await _load_active_listing(session, listing_id)
    if listing.seller_id == buyer_id:
        raise ForbiddenError("You cannot buy your own resale listing.")

    listing.status = ResaleStatus.SOLD
    await session.commit()
    await session.refresh(listing, attribute_names=["product"])
    return listing


async def add_listing_to_cart(
    session: AsyncSession,
    *,
    listing_id: int,
    buyer_id: int,
    now: datetime | None = None,
) -> CartItem:
    """Add an ACTIVE resale listing to the buyer's cart at the resale price.

    Loads the ACTIVE listing (404/409 otherwise), rejects a seller adding their
    own listing (403), then creates a :class:`CartItem` referencing both the
    underlying product and the resale listing, with ``unit_price`` set to the
    discounted resale price. The listing stays ACTIVE until it is bought.
    Returns the created cart item (with product + resale_listing loaded).
    """
    moment = now or _utcnow()
    listing = await _load_active_listing(session, listing_id)
    if listing.seller_id == buyer_id:
        raise ForbiddenError("You cannot add your own resale listing to a cart.")

    cart_item = CartItem(
        user_id=buyer_id,
        product_id=listing.product_id,
        resale_listing_id=listing.id,
        unit_price=listing.resale_price,
        added_at=moment,
    )
    session.add(cart_item)
    await session.commit()
    await session.refresh(cart_item, attribute_names=["product", "resale_listing"])
    return cart_item
