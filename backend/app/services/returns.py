"""Return service — initiation and scanner-pool membership (Requirement 3).

This service owns the side-effecting parts of return *initiation* and the
*scanner-pool* read used by the matching engine and admin dashboard:

* :func:`initiate_return` creates a SCANNING :class:`ReturnOrder` with a 48-hour
  window bound to the initiating seller and the returned product's ASIN
  (Requirements 3.1, 3.2), enforcing the eligibility rule that the referenced
  purchase belongs to the requesting user (Requirement 3.7).
* :func:`scanner_pool_members` returns the discoverable returns — status
  SCANNING with a non-expired window (Requirement 3.3) — for downstream
  matching and admin queries.

The lifecycle state machine, expiry sweep, and transition endpoint live
elsewhere (tasks 5.x / 8.4); this module deliberately does not touch them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AuthError, NotEligibleError
from app.models.enums import ReturnStatus
from app.models.order_history import OrderHistory
from app.models.return_order import ReturnOrder

#: Length of the Return_Window in seconds — exactly 48 hours (Requirement 3.1).
RETURN_WINDOW_SECONDS = 172_800

#: Minimum age, in days, for a purchase to be eligible for resale (Requirement 11.1).
RESALE_ELIGIBLE_AFTER_DAYS = 7


def _utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def _as_aware(moment: datetime) -> datetime:
    """Coerce a possibly-naive datetime to timezone-aware UTC.

    Postgres ``TIMESTAMPTZ`` columns normally hydrate as aware datetimes, but a
    naive value (e.g. from SQLite-backed tests) is treated as UTC so age maths
    never raises on mixed offsets.
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


class SellerOrder:
    """A seller's OrderHistory row joined with its Product and resale gating.

    Plain data holder (not persisted) carrying exactly the fields the ``/orders``
    page and downstream return/resale flows consume: the source
    ``order_history_id``, the product's ``asin``/``name``/``price`` and image
    fields, the ``purchased_at`` timestamp, a computed ``days_since_purchase``,
    and the ``resell_eligible`` flag (purchased more than 7 days ago,
    Requirement 11.1).
    """

    __slots__ = (
        "order_history_id",
        "asin",
        "name",
        "price",
        "image_url",
        "uploaded_image_path",
        "purchased_at",
        "days_since_purchase",
        "resell_eligible",
        "return_eligible",
        "return_status",
    )

    def __init__(
        self,
        *,
        order_history_id: int,
        asin: str,
        name: str,
        price: object,
        image_url: str,
        uploaded_image_path: str | None,
        purchased_at: datetime,
        days_since_purchase: int,
        resell_eligible: bool,
        return_eligible: bool,
        return_status: ReturnStatus | None = None,
    ) -> None:
        self.order_history_id = order_history_id
        self.asin = asin
        self.name = name
        self.price = price
        self.image_url = image_url
        self.uploaded_image_path = uploaded_image_path
        self.purchased_at = purchased_at
        self.days_since_purchase = days_since_purchase
        self.resell_eligible = resell_eligible
        self.return_eligible = return_eligible
        self.return_status = return_status


async def list_seller_orders(
    session: AsyncSession,
    *,
    user_id: int,
    now: datetime | None = None,
) -> list[SellerOrder]:
    """Return the authenticated user's order history joined with each Product.

    Each :class:`SellerOrder` carries the product details plus a computed
    ``days_since_purchase`` and a ``resell_eligible`` flag that is ``True`` when
    ``purchased_at`` is more than 7 days before ``now`` (Requirement 11.1). The
    list is ordered most-recent purchase first and is empty when the user has no
    orders — callers surface an empty collection rather than an error. ``now`` is
    injectable for deterministic testing.
    """
    moment = now or _utcnow()

    stmt = (
        select(OrderHistory)
        .where(OrderHistory.user_id == user_id)
        .options(selectinload(OrderHistory.product))
        .order_by(OrderHistory.purchased_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    order_ids = [order.id for order in rows]
    return_status_by_order_id: dict[int, ReturnStatus] = {}
    if order_ids:
        return_rows = (
            (
                await session.execute(
                    select(ReturnOrder)
                    .where(ReturnOrder.order_history_id.in_(order_ids))
                    .order_by(ReturnOrder.initiated_at.desc(), ReturnOrder.id.desc())
                )
            )
            .scalars()
            .all()
        )
        for return_order in return_rows:
            return_status_by_order_id.setdefault(
                return_order.order_history_id, return_order.status
            )

    orders: list[SellerOrder] = []
    for order in rows:
        product = order.product
        purchased_at = _as_aware(order.purchased_at)
        age = moment - purchased_at
        days_since_purchase = max(0, age.days)
        resell_eligible = age > timedelta(days=RESALE_ELIGIBLE_AFTER_DAYS)
        # A return may only be started within the first 7 days after purchase;
        # older purchases are resale-only (complementary to ``resell_eligible``).
        return_eligible = age <= timedelta(days=RESALE_ELIGIBLE_AFTER_DAYS)
        orders.append(
            SellerOrder(
                order_history_id=order.id,
                asin=product.asin,
                name=product.name,
                price=product.price,
                image_url=product.image_url,
                uploaded_image_path=product.uploaded_image_path,
                purchased_at=purchased_at,
                days_since_purchase=days_since_purchase,
                resell_eligible=resell_eligible,
                return_eligible=return_eligible,
                return_status=return_status_by_order_id.get(order.id),
            )
        )
    return orders


async def initiate_return(
    session: AsyncSession,
    *,
    user_id: int | None,
    order_history_id: int,
    now: datetime | None = None,
) -> ReturnOrder:
    """Create a SCANNING ReturnOrder for ``order_history_id`` on behalf of a user.

    Eligibility (Requirement 3.7):

    * ``user_id`` must identify an authenticated session, else :class:`AuthError`
      (no ReturnOrder created).
    * The referenced :class:`OrderHistory` must exist **and belong to that
      user** (the returned product must be in the requesting user's history),
      else :class:`NotEligibleError` (no ReturnOrder created).

    On success the ReturnOrder is created with status SCANNING,
    ``initiated_at`` set to the current server time, and ``expires_at`` set to
    ``initiated_at`` plus exactly 48 hours / 172,800 s (Requirement 3.1), bound
    to the initiating user's id and the returned product's id and ASIN
    (Requirement 3.2). ``now`` is injectable for deterministic testing.
    """
    if user_id is None:
        # No authenticated Seller session (Requirement 3.7).
        raise AuthError()

    moment = now or _utcnow()

    # Load the source purchase together with its product so we can both verify
    # ownership and copy the denormalized ASIN (Requirement 3.2).
    stmt = (
        select(OrderHistory)
        .where(OrderHistory.id == order_history_id)
        .options(selectinload(OrderHistory.product))
    )
    order_history = (await session.execute(stmt)).scalar_one_or_none()

    if order_history is None or order_history.user_id != user_id:
        # Product/order is not in the requesting user's history (Requirement 3.7).
        raise NotEligibleError()

    # A return may only be started within the first 7 days after purchase;
    # older purchases are resale-only. Enforced server-side so the UI gate
    # cannot be bypassed.
    purchase_age = moment - _as_aware(order_history.purchased_at)
    if purchase_age > timedelta(days=RESALE_ELIGIBLE_AFTER_DAYS):
        raise NotEligibleError(
            "Return initiation is not permitted: this purchase is more than 7 "
            "days old and is eligible for resale instead."
        )

    existing = (
        await session.execute(
            select(ReturnOrder)
            .where(
                ReturnOrder.seller_id == user_id,
                ReturnOrder.order_history_id == order_history.id,
                ReturnOrder.status.in_(
                    (
                        ReturnStatus.SCANNING,
                        ReturnStatus.MATCH_FOUND,
                        ReturnStatus.BUYER_ACCEPTED,
                        ReturnStatus.LOCAL_DELIVERY,
                    )
                ),
            )
            .order_by(ReturnOrder.initiated_at.desc(), ReturnOrder.id.desc())
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    product = order_history.product

    return_order = ReturnOrder(
        seller_id=user_id,
        product_id=order_history.product_id,
        order_history_id=order_history.id,
        asin=product.asin,
        status=ReturnStatus.SCANNING,
        initiated_at=moment,
        expires_at=moment + timedelta(seconds=RETURN_WINDOW_SECONDS),
    )
    session.add(return_order)
    await session.commit()
    await session.refresh(return_order)
    return return_order


async def scanner_pool_members(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> list[ReturnOrder]:
    """Return the discoverable returns in the Return_Scanner_Pool.

    A ReturnOrder is discoverable iff its status is SCANNING **and** its
    ``expires_at`` is strictly later than the current time (Requirement 3.3).
    Used by the matching engine (task 10.1) and the admin dashboard. ``now`` is
    injectable so callers/tests can evaluate the pool at a fixed instant.
    """
    moment = now or _utcnow()
    stmt = select(ReturnOrder).where(
        ReturnOrder.status == ReturnStatus.SCANNING,
        ReturnOrder.expires_at > moment,
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
