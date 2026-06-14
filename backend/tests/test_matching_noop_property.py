"""Property 12 — no eligible candidate leaves match state unchanged (task 10.4).

Feature: amazon-edge-return, Property 12: No eligible candidate leaves match
state unchanged.

For any signal where no ReturnOrder qualifies — the buyer is beyond the 20 km
Match_Radius, there is no SCANNING return for the ASIN, or the only return is the
buyer's own — :func:`run_matching_for_signal` creates no MatchCandidate and
leaves any pre-existing candidates unchanged (Requirement 6.10).

This property needs a database, so we combine Hypothesis with the in-memory
async SQLite + FakeGateway harness from ``tests/test_matching_engine.py``: a
fresh in-memory engine/sessionmaker is built per generated example inside an
async helper invoked via ``asyncio.run`` so each case is fully isolated. A
pre-existing PENDING candidate for an unrelated buyer is seeded so we can assert
the no-op truly leaves prior match state untouched.

**Validates: Requirements 6.10**
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
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

from app.core.matching import MATCH_RADIUS_KM, Point, haversine_km
from app.db.base import Base
from app.models.enums import MatchStatus, ReturnStatus
from app.models.match_candidate import MatchCandidate
from app.models.order_history import OrderHistory
from app.models.product import Product
from app.models.return_order import ReturnOrder
from app.models.user import User
from app.services.analytics import get_active_match_count
from app.services.matching_engine import run_matching_for_signal

# Seeded coordinates (Requirement 2.3/2.4): Priya (seller), Rahul (~5 km buyer).
PRIYA_LAT, PRIYA_LON = 12.9781, 77.6389
RAHUL_LAT, RAHUL_LON = 12.9352, 77.6271

NOW = datetime(2024, 6, 1, 0, 0, 0)

# The three ineligibility scenarios under which matching must be a no-op.
SCENARIOS = ("far", "no_scanning", "own_return")


async def _build_factory() -> tuple[async_sessionmaker, object]:
    """Create a fresh in-memory async SQLite engine + sessionmaker."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    return factory, engine


async def _seed(factory, *, return_status: ReturnStatus) -> dict[str, int | str]:
    """Seed seller/buyers/product/return plus one pre-existing PENDING candidate.

    The pre-existing PENDING candidate belongs to an unrelated ``other_buyer`` so
    we can verify the no-op signal leaves prior match state untouched. The return
    is created with ``return_status`` so the ``no_scanning`` scenario can make it
    EXPIRED (no SCANNING return for the ASIN).
    """
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
        other_buyer = User(
            name="Anita Other",
            email="anita@example.com",
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
        session.add_all([seller, buyer, other_buyer, product])
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
            status=return_status,
            initiated_at=NOW - timedelta(hours=1),
            expires_at=NOW + timedelta(hours=47),
        )
        session.add(ret)
        await session.flush()
        # Pre-existing PENDING candidate for an unrelated buyer (must survive).
        existing = MatchCandidate(
            return_order_id=ret.id,
            buyer_id=other_buyer.id,
            status=MatchStatus.PENDING,
            distance_km=5.0,
            signal_source="cart",
            local_discount=Decimal("598.80"),
            delivery_time_saved_hours=12,
            carbon_avoided_kg=1.2,
            created_at=NOW,
        )
        session.add(existing)
        await session.commit()
        return {
            "seller_id": seller.id,
            "buyer_id": buyer.id,
            "other_buyer_id": other_buyer.id,
            "asin": product.asin,
            "return_id": ret.id,
            "existing_id": existing.id,
        }


async def _run_example(scenario: str, far_off: float) -> None:
    """Seed a fresh DB for ``scenario`` and assert matching is a no-op."""
    return_status = (
        ReturnStatus.EXPIRED if scenario == "no_scanning" else ReturnStatus.SCANNING
    )
    factory, engine = await _build_factory()
    try:
        ids = await _seed(factory, return_status=return_status)

        # Choose the signal buyer + coordinates for the scenario.
        if scenario == "far":
            signal_buyer_id = int(ids["buyer_id"])
            buyer_lat, buyer_lon = PRIYA_LAT + far_off, PRIYA_LON
            # Confirm the buyer is genuinely beyond the radius for this example.
            assert (
                haversine_km(
                    Point(lat=buyer_lat, lon=buyer_lon),
                    Point(lat=PRIYA_LAT, lon=PRIYA_LON),
                )
                > MATCH_RADIUS_KM
            )
        elif scenario == "own_return":
            # The signal buyer is the seller — self-match is excluded.
            signal_buyer_id = int(ids["seller_id"])
            buyer_lat, buyer_lon = PRIYA_LAT, PRIYA_LON
        else:  # no_scanning — return is EXPIRED, so no SCANNING return exists.
            signal_buyer_id = int(ids["buyer_id"])
            buyer_lat, buyer_lon = RAHUL_LAT, RAHUL_LON

        async with factory() as session:
            count_before = await get_active_match_count(session)
            total_before = (
                await session.execute(
                    select(func.count()).select_from(MatchCandidate)
                )
            ).scalar_one()

            match = await run_matching_for_signal(
                session,
                asin=str(ids["asin"]),
                buyer_id=signal_buyer_id,
                signal_source="cart",
                buyer_lat=buyer_lat,
                buyer_lon=buyer_lon,
                now=NOW,
            )

        # No candidate created (Requirement 6.10).
        assert match is None

        async with factory() as session:
            total_after = (
                await session.execute(
                    select(func.count()).select_from(MatchCandidate)
                )
            ).scalar_one()
            # No new candidate, and the pre-existing one is unchanged.
            assert total_after == total_before == 1

            existing = await session.get(MatchCandidate, int(ids["existing_id"]))
            assert existing is not None
            assert existing.status == MatchStatus.PENDING
            assert existing.buyer_id == ids["other_buyer_id"]

            # Active-match count untouched.
            assert await get_active_match_count(session) == count_before
    finally:
        await engine.dispose()


@settings(max_examples=10, deadline=None)
@given(
    scenario=st.sampled_from(SCENARIOS),
    far_off=st.floats(
        min_value=0.25,
        max_value=0.6,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_no_eligible_candidate_leaves_state_unchanged(
    scenario: str, far_off: float
) -> None:
    """Property 12: an ineligible signal creates nothing and changes nothing."""
    asyncio.run(_run_example(scenario, far_off))
