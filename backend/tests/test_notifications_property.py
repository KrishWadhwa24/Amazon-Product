"""Property 15 — PENDING candidates persist while their return is SCANNING
(task 21.3).

Feature: amazon-edge-return, Property 15: PENDING candidates persist while their
return is SCANNING.

For any PENDING :class:`~app.models.match_candidate.MatchCandidate` whose
:class:`~app.models.return_order.ReturnOrder` remains SCANNING and on which no
accept/reject action has occurred, repeatedly calling
``list_pending_for_buyer`` (simulating ``N`` polling cycles) leaves the
candidate PENDING and it continues to be returned each cycle. Serving may stamp
``Notification.delivered_at`` — that is fine — but the MatchCandidate status must
never change from PENDING.

This property is side-effecting, so it runs against the same in-memory async
SQLite harness used by ``tests/test_notifications.py``. Each Hypothesis example
builds a fresh engine/sessionmaker and drives the service via ``asyncio.run``
for full per-example isolation.

Validates: Requirements 8.6
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
from app.models.enums import MatchStatus, NotificationStatus, ReturnStatus
from app.models.match_candidate import MatchCandidate
from app.models.notification import Notification
from app.models.order_history import OrderHistory
from app.models.product import Product
from app.models.return_order import ReturnOrder
from app.models.user import User
from app.services import notifications as notifications_service

PRIYA_LAT, PRIYA_LON = 12.9781, 77.6389
RAHUL_LAT, RAHUL_LON = 12.9352, 77.6271

NOW = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)

SIGNAL_SOURCES = ("cart", "buynow", "wishlist", "viewed")


async def _run_example(
    *,
    cycles: int,
    distance_km: float,
    discount_cents: int,
    delivery_hours: int,
    carbon_kg: float,
    signal_source: str,
) -> None:
    """Seed one PENDING candidate on a SCANNING return, poll ``cycles`` times,
    and assert the candidate stays PENDING and keeps being returned."""
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

        async with factory() as session:
            seller = User(
                name="Priya Sharma",
                email="priya@example.com",
                password_hash="x",
                latitude=PRIYA_LAT,
                longitude=PRIYA_LON,
            )
            buyer = User(
                name="Rahul Verma",
                email="rahul@example.com",
                password_hash="x",
                latitude=RAHUL_LAT,
                longitude=RAHUL_LON,
            )
            product = Product(
                asin="B0SONY520",
                name="Sony WH-CH520 Wireless Headphones",
                price=Decimal("4990.00"),
                rating=4.5,
                review_count=120,
                image_url="https://img.example/sony.jpg",
                estimated_reverse_logistics_cost=Decimal("200.00"),
            )
            session.add_all([seller, buyer, product])
            await session.flush()
            order = OrderHistory(
                user_id=seller.id,
                product_id=product.id,
                purchased_at=NOW - timedelta(days=3),
            )
            session.add(order)
            await session.flush()
            ret = ReturnOrder(
                seller_id=seller.id,
                product_id=product.id,
                order_history_id=order.id,
                asin=product.asin,
                status=ReturnStatus.SCANNING,
                initiated_at=NOW - timedelta(hours=1),
                expires_at=NOW + timedelta(hours=47),
            )
            session.add(ret)
            await session.flush()
            cand = MatchCandidate(
                return_order_id=ret.id,
                buyer_id=buyer.id,
                status=MatchStatus.PENDING,
                distance_km=distance_km,
                signal_source=signal_source,
                local_discount=(Decimal(discount_cents) / Decimal(100)),
                delivery_time_saved_hours=delivery_hours,
                carbon_avoided_kg=carbon_kg,
                created_at=NOW,
            )
            session.add(cand)
            await session.flush()
            session.add(
                Notification(
                    match_candidate_id=cand.id,
                    buyer_id=buyer.id,
                    status=NotificationStatus.PENDING,
                    created_at=NOW,
                )
            )
            await session.commit()
            buyer_id = buyer.id
            cand_id = cand.id

        # Simulate N polling cycles. After every cycle the candidate must still
        # be returned and its persisted status must remain PENDING.
        for _ in range(cycles):
            async with factory() as session:
                views = await notifications_service.list_pending_for_buyer(
                    session, buyer_id, now=NOW
                )

            returned_ids = {v.candidate_id for v in views}
            assert cand_id in returned_ids, (
                "candidate must continue to be returned each polling cycle"
            )

            async with factory() as session:
                persisted = await session.get(MatchCandidate, cand_id)
                assert persisted.status == MatchStatus.PENDING, (
                    "MatchCandidate.status must remain PENDING across polling"
                )

        # Final invariant: status never moved away from PENDING.
        async with factory() as session:
            persisted = await session.get(MatchCandidate, cand_id)
            assert persisted.status == MatchStatus.PENDING
    finally:
        await engine.dispose()


@settings(max_examples=10, deadline=None)
@given(
    cycles=st.integers(min_value=1, max_value=6),
    distance_km=st.floats(
        min_value=0.0, max_value=20.0, allow_nan=False, allow_infinity=False
    ),
    discount_cents=st.integers(min_value=0, max_value=10_000_00),
    delivery_hours=st.integers(min_value=0, max_value=72),
    carbon_kg=st.floats(
        min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False
    ),
    signal_source=st.sampled_from(SIGNAL_SOURCES),
)
def test_pending_persists_under_polling(
    cycles: int,
    distance_km: float,
    discount_cents: int,
    delivery_hours: int,
    carbon_kg: float,
    signal_source: str,
) -> None:
    """Feature: amazon-edge-return, Property 15: PENDING candidates persist while their return is SCANNING.

    Validates: Requirements 8.6
    """
    asyncio.run(
        _run_example(
            cycles=cycles,
            distance_km=distance_km,
            discount_cents=discount_cents,
            delivery_hours=delivery_hours,
            carbon_kg=carbon_kg,
            signal_source=signal_source,
        )
    )
