"""Property-based test for return creation window (task 8.2).

Feature: amazon-edge-return, Property 1: Return creation sets SCANNING and a
48-hour window.

For any valid seller with a product in their order history,
``initiate_return`` produces a ReturnOrder with status SCANNING, ``seller_id``
equal to the initiating user, ``asin`` equal to the product's ASIN, and an
exact 48-hour window (``expires_at - initiated_at == 172,800 s``), regardless of
the ``now`` timestamp or the product's attributes.

The pure logic under test is side-effecting (it persists a ReturnOrder), so the
property is exercised against the same in-memory async SQLite harness used by
``tests/test_returns.py``. Each Hypothesis example builds and seeds a fresh
database and drives ``initiate_return`` via ``asyncio.run``; using a per-example
engine avoids sharing function-scoped async fixtures across Hypothesis examples.

Validates: Requirements 3.1, 3.2
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
from app.models.enums import ReturnStatus
from app.models.order_history import OrderHistory
from app.models.product import Product
from app.models.user import User
from app.services import returns as returns_service
from app.services.returns import RETURN_WINDOW_SECONDS


# --------------------------------------------------------------------------- #
# Hypothesis strategies — vary the `now` timestamp and the product attributes.
# --------------------------------------------------------------------------- #

# `now` is varied across a wide range of timezone-aware UTC datetimes. SQLite
# stores naive datetimes, so the harness compares the exact window length
# (a duration) rather than tz identity, which is unaffected by tz handling.
now_strategy = st.datetimes(
    min_value=datetime(2000, 1, 1, 0, 0, 0),
    max_value=datetime(2100, 1, 1, 0, 0, 0),
)

# Product attributes are varied within their schema invariants (Requirement
# 2.5): non-empty unique ASIN, non-empty name, price > 0, rating in [0, 5],
# review_count >= 0, non-empty image_url, reverse-logistics cost >= 0.
asin_strategy = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", min_size=1, max_size=32
)
name_strategy = st.text(min_size=1, max_size=120).filter(lambda s: s.strip() != "")
price_strategy = st.decimals(
    min_value=Decimal("0.01"), max_value=Decimal("99999999.99"), places=2
)
rating_strategy = st.floats(min_value=0.0, max_value=5.0)
review_count_strategy = st.integers(min_value=0, max_value=1_000_000)
reverse_cost_strategy = st.decimals(
    min_value=Decimal("0.00"), max_value=Decimal("99999999.99"), places=2
)


async def _run_property(
    *,
    now: datetime,
    asin: str,
    name: str,
    price: Decimal,
    rating: float,
    review_count: int,
    reverse_cost: Decimal,
) -> None:
    """Seed a fresh DB, initiate a return, and assert Property 1 holds."""
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

        # Seed a valid seller with the generated product in their history.
        async with factory() as session:
            seller = User(
                name="Seller",
                email="seller@example.com",
                password_hash="x",
                latitude=12.9781,
                longitude=77.6389,
            )
            product = Product(
                asin=asin,
                name=name,
                price=price,
                rating=rating,
                review_count=review_count,
                image_url="https://img.example/p.jpg",
                estimated_reverse_logistics_cost=reverse_cost,
            )
            session.add_all([seller, product])
            await session.flush()
            order = OrderHistory(
                user_id=seller.id,
                product_id=product.id,
                purchased_at=now.replace(tzinfo=timezone.utc) - timedelta(days=2),
            )
            session.add(order)
            await session.commit()
            seller_id = seller.id
            order_history_id = order.id

        # Exercise the system under test with the generated `now`.
        async with factory() as session:
            order = await returns_service.initiate_return(
                session,
                user_id=seller_id,
                order_history_id=order_history_id,
                now=now.replace(tzinfo=timezone.utc),
            )

            assert order.status == ReturnStatus.SCANNING
            assert order.seller_id == seller_id
            assert order.asin == asin
            window = order.expires_at - order.initiated_at
            assert window.total_seconds() == RETURN_WINDOW_SECONDS == 172_800
    finally:
        await engine.dispose()


@settings(max_examples=10, deadline=None)
@given(
    now=now_strategy,
    asin=asin_strategy,
    name=name_strategy,
    price=price_strategy,
    rating=rating_strategy,
    review_count=review_count_strategy,
    reverse_cost=reverse_cost_strategy,
)
def test_return_creation_sets_scanning_and_48h_window(
    now: datetime,
    asin: str,
    name: str,
    price: Decimal,
    rating: float,
    review_count: int,
    reverse_cost: Decimal,
) -> None:
    """Feature: amazon-edge-return, Property 1: Return creation sets SCANNING and a 48-hour window.

    Validates: Requirements 3.1, 3.2
    """
    asyncio.run(
        _run_property(
            now=now,
            asin=asin,
            name=name,
            price=price,
            rating=rating,
            review_count=review_count,
            reverse_cost=reverse_cost,
        )
    )
