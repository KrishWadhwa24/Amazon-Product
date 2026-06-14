"""Property 16 — candidate accept/reject transitions (task 11.2).

Feature: amazon-edge-return, Property 16: Candidate accept/reject transitions.

For any PENDING :class:`MatchCandidate`, the owning buyer accepting it yields
``ACCEPTED`` and rejecting it yields ``REJECTED``. The choice of action and the
candidate's varied attributes (distance, signal source, cached deal impact)
never change this outcome.

This property is side-effecting (it persists/mutates rows), so it is exercised
against the same in-memory async SQLite harness used by ``tests/test_matches.py``.
Each Hypothesis example builds a fresh in-memory engine/sessionmaker, seeds a
SCANNING return with a single PENDING candidate, and drives the service via
``asyncio.run`` so every example is fully isolated.

Validates: Requirements 9.2, 9.3
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.enums import MatchStatus, ReturnStatus
from app.models.match_candidate import MatchCandidate
from app.models.order_history import OrderHistory
from app.models.product import Product
from app.models.return_order import ReturnOrder
from app.models.user import User
from app.services import matches as matches_service

# Seeded seller / buyer coordinates (Requirement 2.3).
PRIYA_LAT, PRIYA_LON = 12.9781, 77.6389
RAHUL_LAT, RAHUL_LON = 12.9352, 77.6271

# SQLite deserializes naive datetimes; keep the reference clock naive to match.
NOW = datetime(2024, 6, 1, 0, 0, 0)

SIGNAL_SOURCES = ("cart", "buynow", "wishlist", "viewed")


async def _run_example(
    *,
    action: str,
    distance_km: float,
    signal_source: str,
    discount: Decimal,
    delivery_hours: int,
    carbon_kg: float,
) -> None:
    """Seed a fresh DB with one PENDING candidate and assert Property 16."""
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
                local_discount=discount,
                delivery_time_saved_hours=delivery_hours,
                carbon_avoided_kg=carbon_kg,
                created_at=NOW,
            )
            session.add(cand)
            await session.commit()
            buyer_id = buyer.id
            cand_id = cand.id

        async with factory() as session:
            stmt = (
                select(MatchCandidate)
                .where(MatchCandidate.id == cand_id)
                .options(selectinload(MatchCandidate.return_order))
            )
            candidate = (await session.execute(stmt)).scalar_one()

            if action == "accept":
                result = await matches_service.accept_match(
                    session, candidate, user_id=buyer_id
                )
                # Owning buyer accept => ACCEPTED (Requirement 9.2).
                assert result.status == MatchStatus.ACCEPTED
                expected = MatchStatus.ACCEPTED
            else:
                result = await matches_service.reject_match(
                    session, candidate, user_id=buyer_id
                )
                # Owning buyer reject => REJECTED (Requirement 9.3).
                assert result.status == MatchStatus.REJECTED
                expected = MatchStatus.REJECTED

        # Reload independently to confirm the persisted status.
        async with factory() as session:
            persisted = await session.get(MatchCandidate, cand_id)
            assert persisted.status == expected
    finally:
        await engine.dispose()


@settings(max_examples=10, deadline=None)
@given(
    action=st.sampled_from(("accept", "reject")),
    distance_km=st.floats(
        min_value=0.0, max_value=20.0, allow_nan=False, allow_infinity=False
    ),
    signal_source=st.sampled_from(SIGNAL_SOURCES),
    discount=st.decimals(
        min_value=Decimal("0.00"), max_value=Decimal("748.50"), places=2
    ),
    delivery_hours=st.integers(min_value=0, max_value=72),
    carbon_kg=st.floats(
        min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False
    ),
)
def test_accept_reject_transitions(
    action: str,
    distance_km: float,
    signal_source: str,
    discount: Decimal,
    delivery_hours: int,
    carbon_kg: float,
) -> None:
    """Feature: amazon-edge-return, Property 16: Candidate accept/reject transitions.

    Validates: Requirements 9.2, 9.3
    """
    asyncio.run(
        _run_example(
            action=action,
            distance_km=distance_km,
            signal_source=signal_source,
            discount=discount,
            delivery_hours=delivery_hours,
            carbon_kg=carbon_kg,
        )
    )
