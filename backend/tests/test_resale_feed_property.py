"""Property 23 — resale feed is active-only, ordered, and fully joined
(task 18.2).

Feature: amazon-edge-return, Property 23: Resale feed is active-only, ordered,
and fully joined.

For any set of resale listings (a mix of ACTIVE / SOLD / REMOVED with distinct
``listed_at`` timestamps), ``resale.list_active_feed`` returns *exactly* the
ACTIVE listings, ordered by ``listed_at`` most-recent-first, each exposing its
joined :class:`Product` (with a non-empty ``image_url``), a non-empty
``condition_image_url``, and the original :class:`OrderHistory` purchase date.

This property is side-effecting, so it runs against the same in-memory async
SQLite harness used by ``tests/test_resale.py``. Each Hypothesis example builds
a fresh engine/sessionmaker, seeds ``N`` listings with random statuses and
distinct ``listed_at`` timestamps, and drives the service via ``asyncio.run``
for full per-example isolation.

Validates: Requirements 12.1, 12.7
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.enums import ConditionGrade, ResaleStatus
from app.models.order_history import OrderHistory
from app.models.product import Product
from app.models.resale_listing import ResaleListing
from app.models.user import User
from app.services import resale as resale_service

BASE_LISTED = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
BASE_PURCHASE = datetime(2023, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

_STATUSES = list(ResaleStatus)
_GRADES = list(ConditionGrade)


async def _run_example(*, statuses: list[ResaleStatus], offsets: list[int]) -> None:
    """Seed ``len(statuses)`` listings then assert Property 23 on the feed.

    ``offsets`` are distinct minute offsets driving distinct ``listed_at``
    timestamps; ``statuses[i]`` is the status of listing ``i``.
    """
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

        # Maps the seeded listing id -> expected (listed_at, purchased_at,
        # product image_url, condition_image_url) for ACTIVE listings only.
        expected: dict[int, tuple[datetime, datetime, str, str]] = {}

        async with factory() as session:
            seller = User(
                name="Priya Sharma",
                email="priya@example.com",
                password_hash="x",
                latitude=12.9781,
                longitude=77.6389,
            )
            session.add(seller)
            await session.flush()

            for i, (status, offset) in enumerate(zip(statuses, offsets)):
                product = Product(
                    asin=f"B0PROD{i:04d}",
                    name=f"Product {i}",
                    price=Decimal("4990.00"),
                    rating=4.5,
                    review_count=120,
                    image_url=f"https://img.example/prod-{i}.jpg",
                    estimated_reverse_logistics_cost=Decimal("200.00"),
                )
                session.add(product)
                await session.flush()

                purchased_at = BASE_PURCHASE + timedelta(minutes=offset)
                order = OrderHistory(
                    user_id=seller.id,
                    product_id=product.id,
                    purchased_at=purchased_at,
                )
                session.add(order)
                await session.flush()

                listed_at = BASE_LISTED + timedelta(minutes=offset)
                listing = ResaleListing(
                    product_id=product.id,
                    order_history_id=order.id,
                    seller_id=seller.id,
                    status=status,
                    condition_grade=_GRADES[i % len(_GRADES)],
                    resale_price=Decimal("3000.00"),
                    condition_image_url=f"https://img.example/cond-{i}.jpg",
                    listed_at=listed_at,
                )
                session.add(listing)
                await session.flush()

                if status == ResaleStatus.ACTIVE:
                    expected[listing.id] = (
                        listed_at,
                        purchased_at,
                        product.image_url,
                        listing.condition_image_url,
                    )
            await session.commit()

        async with factory() as session:
            feed = await resale_service.list_active_feed(session)

            returned_ids = [item.listing.id for item in feed]

            # Exactly the ACTIVE listings (no SOLD/REMOVED), newest-first by
            # listed_at (Requirement 12.1).
            expected_order = [
                lid
                for lid, _ in sorted(
                    expected.items(), key=lambda kv: kv[1][0], reverse=True
                )
            ]
            assert returned_ids == expected_order
            assert set(returned_ids) == set(expected)

            # listed_at is strictly descending across the returned feed.
            listed_values = [item.listing.listed_at for item in feed]
            assert listed_values == sorted(listed_values, reverse=True)

            # Each item is fully joined: non-empty product image_url, non-empty
            # condition_image_url, and the correct original purchase date
            # (Requirements 12.1, 12.7).
            for item in feed:
                exp_listed, exp_purchased, exp_img, exp_cond = expected[
                    item.listing.id
                ]
                assert item.listing.status == ResaleStatus.ACTIVE
                assert item.listing.product is not None
                assert item.listing.product.image_url == exp_img
                assert item.listing.product.image_url.strip() != ""
                assert item.listing.condition_image_url == exp_cond
                assert item.listing.condition_image_url.strip() != ""
                assert item.original_purchased_at.replace(
                    tzinfo=None
                ) == exp_purchased.replace(tzinfo=None)
    finally:
        await engine.dispose()


@settings(max_examples=10, deadline=None)
@given(data=st.data())
def test_resale_feed_active_only_ordered_fully_joined(data) -> None:
    """Feature: amazon-edge-return, Property 23: Resale feed is active-only, ordered, and fully joined.

    Validates: Requirements 12.1, 12.7
    """
    n = data.draw(st.integers(min_value=0, max_value=8), label="listing_count")
    statuses = data.draw(
        st.lists(st.sampled_from(_STATUSES), min_size=n, max_size=n),
        label="statuses",
    )
    # Distinct minute offsets -> distinct listed_at timestamps.
    offsets = data.draw(
        st.lists(
            st.integers(min_value=0, max_value=1_000_000),
            min_size=n,
            max_size=n,
            unique=True,
        ),
        label="offsets",
    )
    asyncio.run(_run_example(statuses=statuses, offsets=offsets))
