"""Shop router — product catalog reads + buyer demand-signal endpoints.

This router backs the buyer storefront (tasks 20.1/20.2). It exposes two
read-only catalog endpoints the Next.js catalog/PDP pages consume, plus the four
demand-signal endpoints that record buyer purchase intent into the Redis
inverted geospatial index and synchronously run the Matching_Engine
(Requirements 4.1-4.7, 6.x, 1.8).

Catalog reads (public):
* ``GET /api/products``        — the seeded product catalog.
* ``GET /api/products/{asin}`` — a single product (``404`` when missing).

Demand-signal endpoints (authenticated buyer required):
* ``POST /api/cart``     — persist a CartItem AND record the ``cart`` signal +
  matching; ``201`` with the cart item and whether a match was created
  (Requirements 4.1, 1.8).
* ``GET  /api/cart``     — the buyer's cart items joined with product info.
* ``POST /api/buynow``   — record the ``buynow`` signal + matching; ``201``.
* ``POST /api/wishlist`` — record the ``wishlist`` signal + matching; ``201``.
* ``POST /api/view``     — record the ``viewed`` signal + matching; ``202``.

Each demand endpoint resolves the active buyer id from the signed session cookie
via :func:`require_current_user_id` (Requirement 1.4), reads that buyer's
latitude/longitude from the User row, and calls
:func:`app.services.matching_engine.record_and_match` with the buyer's
coordinates so a successful signal triggers matching. The Redis gateway is
injected through the :func:`get_gateway` dependency (defaulting to the real
shared gateway) so tests can override it with an in-memory fake.

Error mapping:
* :class:`~app.core.errors.InvalidLocationError` -> ``400 INVALID_LOCATION``
  (Requirement 4.6), rendered by the shared domain-error handler.
* :class:`~app.db.redis_gateway.SignalStorageError` is wrapped as
  :class:`~app.core.errors.SignalNotRecordedError` -> ``502
  SIGNAL_NOT_RECORDED`` so a failed Redis write is never reported as success
  (Requirement 4.7).
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_current_user_id
from app.core.errors import (
    AuthError,
    ProductNotFoundError,
    SignalNotRecordedError,
    UnsupportedImageError,
)
from app.db.redis_gateway import RedisGateway, SignalStorageError, get_gateway
from app.db.session import get_session
from app.models.cart_item import CartItem
from app.models.product import Product
from app.models.user import User
from app.services.matching_engine import record_and_match

router = APIRouter(prefix="/api", tags=["shop"])


def get_redis_gateway() -> RedisGateway:
    """FastAPI dependency returning the shared Redis gateway.

    Defaults to the real memoized gateway; tests override this with an in-memory
    fake so demand recording succeeds without a live Redis server.
    """
    return get_gateway()


# --------------------------------------------------------------------------- #
# Response models
# --------------------------------------------------------------------------- #


class ProductResource(BaseModel):
    """Serialized Product for the catalog/PDP reads (task 20.1)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    asin: str
    name: str
    price: Decimal
    rating: float
    review_count: int
    image_url: str
    uploaded_image_path: str | None = None


class CartItemProductResource(BaseModel):
    """Product fields surfaced alongside a cart item."""

    model_config = ConfigDict(from_attributes=True)

    asin: str
    name: str
    price: Decimal
    image_url: str
    uploaded_image_path: str | None = None


class CartItemResource(BaseModel):
    """A single cart item joined with its product (GET /api/cart).

    ``unit_price`` is the price charged for the line — the catalog price for an
    ordinary item, or the discounted resale price for an open-box resale line
    (in which case ``resale_listing_id`` and the condition fields are set).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    added_at: datetime
    unit_price: Decimal | None = None
    resale_listing_id: int | None = None
    condition_grade: str | None = None
    condition_image_url: str | None = None
    product: CartItemProductResource


class AsinRequest(BaseModel):
    """Request body carrying the target product ASIN for a demand signal."""

    asin: str


class AddToCartResponse(BaseModel):
    """``201`` response for ``POST /api/cart``.

    Carries the created cart item plus ``match_created`` indicating whether the
    triggered matching produced a PENDING local-deal candidate, which the
    frontend uses to surface the nearby-return notification (Requirement 1.8).
    """

    cart_item: CartItemResource
    match_created: bool


class SignalResponse(BaseModel):
    """Generic demand-signal acknowledgement for buynow/wishlist/view."""

    ok: bool
    match_created: bool


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _get_product_or_404(session: AsyncSession, asin: str) -> Product:
    """Return the Product for ``asin`` or raise :class:`ProductNotFoundError`."""
    product = (
        await session.execute(select(Product).where(Product.asin == asin))
    ).scalar_one_or_none()
    if product is None:
        raise ProductNotFoundError(asin)
    return product


async def _resolve_buyer(session: AsyncSession, buyer_id: int) -> User:
    """Return the active buyer's User row or raise ``401`` when missing."""
    user = (
        await session.execute(select(User).where(User.id == buyer_id))
    ).scalar_one_or_none()
    if user is None:
        # A signed session that no longer resolves to a user is treated as no
        # active session (Requirement 1.4).
        raise AuthError()
    return user


async def _record(
    session: AsyncSession,
    *,
    intent: str,
    asin: str,
    buyer: User,
    gateway: RedisGateway,
):
    """Record a demand signal and run matching, mapping storage failures.

    Wraps :func:`record_and_match` so a :class:`SignalStorageError` (the Redis
    write failing) becomes :class:`SignalNotRecordedError` -> ``502`` rather than
    a 500, honoring Requirement 4.7. Returns the ``(SignalResult, match)`` tuple.
    """
    try:
        return await record_and_match(
            session,
            intent,
            asin,
            buyer.id,
            buyer.longitude,
            buyer.latitude,
            gateway=gateway,
        )
    except SignalStorageError as exc:
        raise SignalNotRecordedError() from exc


# --------------------------------------------------------------------------- #
# Catalog reads (task 20.1)
# --------------------------------------------------------------------------- #


@router.get(
    "/products",
    response_model=list[ProductResource],
    summary="List the seeded product catalog",
)
async def list_products(
    session: AsyncSession = Depends(get_session),
) -> list[ProductResource]:
    """Return all products, ordered by id, for the storefront catalog grid."""
    products = (
        (await session.execute(select(Product).order_by(Product.id))).scalars().all()
    )
    return [ProductResource.model_validate(p) for p in products]


@router.get(
    "/products/{asin}",
    response_model=ProductResource,
    summary="Get a single product by ASIN",
)
async def get_product(
    asin: str,
    session: AsyncSession = Depends(get_session),
) -> ProductResource:
    """Return one product by ASIN, or ``404`` when no such product exists."""
    product = await _get_product_or_404(session, asin)
    return ProductResource.model_validate(product)


# Accepted upload content types and their canonical file extensions.
_IMAGE_EXT_BY_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
}
# Reject uploads larger than 5 MB to keep the demo store small.
_MAX_IMAGE_BYTES = 5 * 1024 * 1024
# Directory where uploaded photos are written (served at /uploads by main.py).
_UPLOADS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "uploads",
)


@router.post(
    "/products/{asin}/image",
    response_model=ProductResource,
    summary="Upload a product photo (sets uploaded_image_path)",
)
async def upload_product_image(
    asin: str,
    request: Request,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> ProductResource:
    """Upload a real photo for a product and store it as ``uploaded_image_path``.

    Validates that the upload is an image (``400 UNSUPPORTED_IMAGE`` otherwise),
    writes it under the backend ``uploads/`` directory, and stores an absolute
    URL (``{base_url}uploads/{file}``) on the product so the frontend ``<img>``
    loads it directly from the backend. Returns the updated product; the catalog,
    detail, cart, and orders surfaces then prefer this photo over the placeholder
    (``404 PRODUCT_NOT_FOUND`` when the ASIN is unknown).
    """
    product = await _get_product_or_404(session, asin)

    content_type = (file.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise UnsupportedImageError(content_type)

    data = await file.read()
    if not data or len(data) > _MAX_IMAGE_BYTES:
        raise UnsupportedImageError(content_type)

    # Choose a safe extension from the original filename, falling back to the
    # content type. Reject anything that isn't a short alphanumeric extension.
    ext = os.path.splitext(file.filename or "")[1].lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,5}", ext):
        ext = _IMAGE_EXT_BY_TYPE.get(content_type, ".img")

    safe_asin = re.sub(r"[^A-Za-z0-9_-]", "", asin) or "product"
    filename = f"{safe_asin}-{uuid.uuid4().hex[:8]}{ext}"

    os.makedirs(_UPLOADS_DIR, exist_ok=True)
    with open(os.path.join(_UPLOADS_DIR, filename), "wb") as fh:
        fh.write(data)

    base = str(request.base_url).rstrip("/")
    product.uploaded_image_path = f"{base}/uploads/{filename}"
    await session.commit()
    await session.refresh(product)

    return ProductResource.model_validate(product)


# --------------------------------------------------------------------------- #
# Demand-signal endpoints (task 20.2)
# --------------------------------------------------------------------------- #


@router.post(
    "/cart",
    status_code=status.HTTP_201_CREATED,
    response_model=AddToCartResponse,
    summary="Add a product to the cart and record a cart demand signal",
)
async def add_to_cart(
    body: AsinRequest,
    buyer_id: int = Depends(require_current_user_id),
    session: AsyncSession = Depends(get_session),
    gateway: RedisGateway = Depends(get_redis_gateway),
) -> AddToCartResponse:
    """Persist a CartItem and record the ``cart`` demand signal + matching.

    Resolves the active buyer, verifies the product exists (``404`` otherwise),
    records the cart signal into the geospatial index, and runs the
    Matching_Engine (Requirement 4.1). ``match_created`` reports whether a
    PENDING local-deal candidate resulted, which the frontend turns into the
    in-app nearby-return notification (Requirement 1.8). Returns ``201`` with the
    cart item. An invalid buyer location maps to ``400 INVALID_LOCATION`` and a
    failed Redis write to ``502 SIGNAL_NOT_RECORDED`` (Requirements 4.6, 4.7).
    """
    buyer = await _resolve_buyer(session, buyer_id)
    product = await _get_product_or_404(session, body.asin)

    cart_item = CartItem(
        user_id=buyer.id,
        product_id=product.id,
        unit_price=product.price,
        added_at=datetime.now(timezone.utc),
    )
    session.add(cart_item)
    await session.commit()
    await session.refresh(cart_item, attribute_names=["product"])

    _, match = await _record(
        session, intent="cart", asin=body.asin, buyer=buyer, gateway=gateway
    )

    return AddToCartResponse(
        cart_item=CartItemResource(
            id=cart_item.id,
            product_id=cart_item.product_id,
            added_at=cart_item.added_at,
            unit_price=cart_item.unit_price,
            resale_listing_id=cart_item.resale_listing_id,
            condition_grade=None,
            condition_image_url=None,
            product=CartItemProductResource.model_validate(cart_item.product),
        ),
        match_created=match is not None,
    )


@router.delete(
    "/cart",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear all cart items for the active buyer",
)
async def clear_cart(
    buyer_id: int = Depends(require_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete every CartItem row belonging to the active buyer.

    Called by the frontend immediately after an order is placed so the cart is
    emptied. Returns ``204 No Content`` on success.
    """
    from sqlalchemy import delete as sql_delete

    await session.execute(
        sql_delete(CartItem).where(CartItem.user_id == buyer_id)
    )
    await session.commit()


@router.get(
    "/cart",
    response_model=list[CartItemResource],
    summary="List the active buyer's cart items",
)
async def get_cart(
    buyer_id: int = Depends(require_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> list[CartItemResource]:
    """Return the active buyer's cart items joined with product info."""
    items = (
        (
            await session.execute(
                select(CartItem)
                .where(CartItem.user_id == buyer_id)
                .options(
                    selectinload(CartItem.product),
                    selectinload(CartItem.resale_listing),
                )
                .order_by(CartItem.added_at, CartItem.id)
            )
        )
        .scalars()
        .all()
    )
    resources: list[CartItemResource] = []
    for item in items:
        listing = item.resale_listing
        resources.append(
            CartItemResource(
                id=item.id,
                product_id=item.product_id,
                added_at=item.added_at,
                unit_price=item.unit_price
                if item.unit_price is not None
                else item.product.price,
                resale_listing_id=item.resale_listing_id,
                condition_grade=(
                    listing.condition_grade.value if listing is not None else None
                ),
                condition_image_url=(
                    listing.condition_image_url if listing is not None else None
                ),
                product=CartItemProductResource.model_validate(item.product),
            )
        )
    return resources


@router.post(
    "/buynow",
    status_code=status.HTTP_201_CREATED,
    response_model=SignalResponse,
    summary="Record a buy-now demand signal",
)
async def buy_now(
    body: AsinRequest,
    buyer_id: int = Depends(require_current_user_id),
    session: AsyncSession = Depends(get_session),
    gateway: RedisGateway = Depends(get_redis_gateway),
) -> SignalResponse:
    """Record the ``buynow`` demand signal + matching (Requirement 4.2)."""
    buyer = await _resolve_buyer(session, buyer_id)
    await _get_product_or_404(session, body.asin)
    _, match = await _record(
        session, intent="buynow", asin=body.asin, buyer=buyer, gateway=gateway
    )
    return SignalResponse(ok=True, match_created=match is not None)


@router.post(
    "/wishlist",
    status_code=status.HTTP_201_CREATED,
    response_model=SignalResponse,
    summary="Record a wishlist demand signal",
)
async def add_to_wishlist(
    body: AsinRequest,
    buyer_id: int = Depends(require_current_user_id),
    session: AsyncSession = Depends(get_session),
    gateway: RedisGateway = Depends(get_redis_gateway),
) -> SignalResponse:
    """Record the ``wishlist`` demand signal + matching (Requirement 4.3)."""
    buyer = await _resolve_buyer(session, buyer_id)
    await _get_product_or_404(session, body.asin)
    _, match = await _record(
        session, intent="wishlist", asin=body.asin, buyer=buyer, gateway=gateway
    )
    return SignalResponse(ok=True, match_created=match is not None)


@router.post(
    "/view",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SignalResponse,
    summary="Record a product-view demand signal",
)
async def record_view(
    body: AsinRequest,
    buyer_id: int = Depends(require_current_user_id),
    session: AsyncSession = Depends(get_session),
    gateway: RedisGateway = Depends(get_redis_gateway),
) -> SignalResponse:
    """Record the ``viewed`` demand signal + matching; ``202`` (Requirement 4.4)."""
    buyer = await _resolve_buyer(session, buyer_id)
    await _get_product_or_404(session, body.asin)
    _, match = await _record(
        session, intent="viewed", asin=body.asin, buyer=buyer, gateway=gateway
    )
    return SignalResponse(ok=True, match_created=match is not None)
