"""Property-based test for resale listing validation (task 17.2).

Feature: amazon-edge-return, Property 21: Resale listing validation.

For any resale request, ``create_listing`` creates a ResaleListing *if and only
if* the ``condition_grade`` is one of {"Like New", "Good", "Fair"}, the
``condition_image_url`` is a non-empty string, and the ``resale_price`` satisfies
``0 < resale_price <= product.price``. On success the listing has status ACTIVE,
the provided grade/image, a price within bound, and ``listed_at`` equal to the
supplied ``now``; otherwise no listing is created and the appropriate validation
error is raised.

The logic under test persists a ResaleListing, so the property is exercised
against the same in-memory async SQLite harness used by ``tests/test_resale.py``
(a seeded seller + product + owned order). Each Hypothesis example builds and
seeds a fresh in-memory database and drives ``create_listing`` via
``asyncio.run``; the per-example engine keeps every case fully isolated.

Validates: Requirements 11.2, 11.3, 11.4, 11.6, 11.7
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.errors import (
    InvalidResalePriceError,
    MissingImageError,
    UnsupportedGradeError,
)
from app.db.base import Base
from app.models.enums import ConditionGrade, ResaleStatus
from app.models.order_history import OrderHistory
from app.models.product import Product
from app.models.resale_listing import ResaleListing
from app.models.user import User
from app.services import resale as resale_service


# The seeded original Product price; resale prices are generated to straddle it.
PRODUCT_PRICE = Decimal("4990.00")
VALID_GRADES = ("Like New", "Good", "Fair")


# --------------------------------------------------------------------------- #
# Hypothesis strategies — vary grade (inside/outside the set), image
# (empty/non-empty), price (<=0, within range, > product price), and `now`.
# --------------------------------------------------------------------------- #

grade_strategy = st.one_of(
    # Inside the accepted set.
    st.sampled_from(VALID_GRADES),
    # Outside the set: lookalikes, casing variants, and arbitrary text.
    st.sampled_from(
        ["Excellent", "Mint", "New", "like new", "good", "FAIR", "Poor", "", "  "]
    ),
    st.text(max_size=12),
)

image_strategy = st.one_of(
    # Empty / whitespace-only -> invalid.
    st.sampled_from(["", " ", "   ", "\t", "\n", "  \t "]),
    # Arbitrary text (may or may not be whitespace-only) and a concrete URL.
    st.text(max_size=40),
    st.just("https://img.example/live-condition.jpg"),
)

# Prices spanning negatives, zero, within (0, price], and above the ceiling.
price_strategy = st.decimals(
    min_value=Decimal("-50.00"),
    max_value=Decimal("10000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

now_strategy = st.datetimes(
    min_value=datetime(2000, 1, 1, 0, 0, 0),
    max_value=datetime(2100, 1, 1, 0, 0, 0),
)


def _expected_error(grade: str, image: str, price: Decimal):
    """Return the validation error class expected for an invalid request.

    Mirrors ``create_listing``'s documented precedence: image is checked first,
    then grade, then (ownership, always valid here) and finally price. Returns
    ``None`` when the request is fully valid.
    """
    if not isinstance(image, str) or not image.strip():
        return MissingImageError
    if grade not in VALID_GRADES:
        return UnsupportedGradeError
    if not (Decimal("0") < price <= PRODUCT_PRICE):
        return InvalidResalePriceError
    return None


async def _count_listings(session: AsyncSession) -> int:
    stmt = select(func.count()).select_from(ResaleListing)
    return (await session.execute(stmt)).scalar_one()


async def _run_property(
    *, grade: str, image: str, price: Decimal, now: datetime
) -> None:
    """Seed a fresh DB, attempt a listing, and assert Property 21 holds."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )

        # Seed a valid seller with the product in their order history.
        async with factory() as session:
            seller = User(
                name="Priya Sharma",
                email="priya@example.com",
                password_hash="x",
                latitude=12.9781,
                longitude=77.6389,
            )
            product = Product(
                asin="B0SONY520",
                name="Sony WH-CH520 Wireless Headphones",
                price=PRODUCT_PRICE,
                rating=4.5,
                review_count=120,
                image_url="https://img.example/sony.jpg",
                estimated_reverse_logistics_cost=Decimal("200.00"),
            )
            session.add_all([seller, product])
            await session.flush()
            order = OrderHistory(
                user_id=seller.id,
                product_id=product.id,
                purchased_at=datetime.now(timezone.utc) - timedelta(days=30),
            )
            session.add(order)
            await session.commit()
            seller_id = seller.id
            order_history_id = order.id

        moment = now.replace(tzinfo=timezone.utc)
        expected_error = _expected_error(grade, image, price)

        async with factory() as session:
            if expected_error is None:
                # --- Success branch: a listing must be created as specified. ---
                listing = await resale_service.create_listing(
                    session,
                    seller_id=seller_id,
                    order_history_id=order_history_id,
                    condition_grade=grade,
                    condition_image_url=image,
                    resale_price=price,
                    now=moment,
                )
                assert listing.status == ResaleStatus.ACTIVE
                assert listing.condition_grade == ConditionGrade(grade)
                assert listing.condition_image_url == image
                assert listing.resale_price == price
                assert Decimal("0") < listing.resale_price <= PRODUCT_PRICE
                assert listing.seller_id == seller_id
                assert listing.listed_at.replace(tzinfo=None) == moment.replace(
                    tzinfo=None
                )
                assert await _count_listings(session) == 1
            else:
                # --- Rejection branch: correct error, no listing created. ---
                try:
                    await resale_service.create_listing(
                        session,
                        seller_id=seller_id,
                        order_history_id=order_history_id,
                        condition_grade=grade,
                        condition_image_url=image,
                        resale_price=price,
                        now=moment,
                    )
                except expected_error:
                    pass
                else:
                    raise AssertionError(
                        f"expected {expected_error.__name__} for "
                        f"grade={grade!r} image={image!r} price={price}"
                    )
                assert await _count_listings(session) == 0
    finally:
        await engine.dispose()


@settings(max_examples=10, deadline=None)
@given(
    grade=grade_strategy,
    image=image_strategy,
    price=price_strategy,
    now=now_strategy,
)
def test_resale_listing_validation(
    grade: str, image: str, price: Decimal, now: datetime
) -> None:
    """Feature: amazon-edge-return, Property 21: Resale listing validation.

    Validates: Requirements 11.2, 11.3, 11.4, 11.6, 11.7
    """
    asyncio.run(_run_property(grade=grade, image=image, price=price, now=now))
