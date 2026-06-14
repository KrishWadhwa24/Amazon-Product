"""Property 10 — match creation produces a PENDING candidate and bumps the
active-match count (task 10.2).

Feature: amazon-edge-return, Property 10: Match creation produces a PENDING
candidate and bumps the active-match count.

For any eligible nearby buyer/return scenario within the 20 km Match_Radius with
no existing PENDING candidate, :func:`run_matching_for_signal` creates exactly
one PENDING :class:`MatchCandidate` carrying the rounded ``distance_km`` and the
given ``signal_source``, and increments the active-match count by exactly one.

This property needs a database, so we combine Hypothesis with the in-memory
async SQLite + FakeGateway harness from ``tests/test_matching_engine.py``: a
fresh in-memory engine/sessionmaker is built per generated example inside an
async helper invoked via ``asyncio.run`` so each case is fully isolated.

**Validates: Requirements 6.5, 6.7, 9.1**
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
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

# Seeded seller coordinates (Requirement 2.3): Priya Sharma.
PRIYA_LAT, PRIYA_LON = 12.9781, 77.6389

# SQLite deserializes naive datetimes, so keep the reference clock naive to match
# what the stored ReturnOrder.expires_at deserializes to (see test_matching_engine).
NOW = datetime(2024, 6, 1, 0, 0, 0)

# Signal sources that may be stamped onto a candidate (Requirement 6.5).
SIGNAL_SOURCES = ("cart", "buynow", "wishlist", "viewed")

# Coordinate offsets kept small enough that the buyer always stays inside the
# 20 km Match_Radius. At ~12.98° latitude, 0.1° ≈ 11 km on each axis, so the
# worst-case combined distance (~15.6 km) is comfortably within 20 km.
_MAX_OFFSET_DEG = 0.1


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


async def _seed_scanning_return(factory) -> dict[str, int | str]:
    """Seed Priya (seller), Rahul (buyer), a product, order, and SCANNING return."""
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
            latitude=PRIYA_LAT,  # overwritten by the signal coords at call time
            longitude=PRIYA_LON,
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
        await session.commit()
        return {
            "seller_id": seller.id,
            "buyer_id": buyer.id,
            "asin": product.asin,
            "return_id": ret.id,
        }


async def _run_example(signal_source: str, lat_off: float, lon_off: float) -> None:
    """Seed a fresh DB and assert the Property 10 expectations for one example."""
    factory, engine = await _build_factory()
    try:
        ids = await _seed_scanning_return(factory)
        buyer_lat = PRIYA_LAT + lat_off
        buyer_lon = PRIYA_LON + lon_off

        # The buyer must be inside the radius for an eligible scenario.
        expected_distance = haversine_km(
            Point(lat=buyer_lat, lon=buyer_lon), Point(lat=PRIYA_LAT, lon=PRIYA_LON)
        )
        assert expected_distance <= MATCH_RADIUS_KM

        async with factory() as session:
            # Precondition: no PENDING candidate and a zero active-match count.
            count_before = await get_active_match_count(session)
            assert count_before == 0

            match = await run_matching_for_signal(
                session,
                asin=str(ids["asin"]),
                buyer_id=int(ids["buyer_id"]),
                signal_source=signal_source,
                buyer_lat=buyer_lat,
                buyer_lon=buyer_lon,
                now=NOW,
            )

        # Exactly one PENDING candidate carrying the rounded distance + source.
        assert match is not None
        assert match.status == MatchStatus.PENDING
        assert match.signal_source == signal_source
        assert match.distance_km == pytest.approx(expected_distance, abs=1e-6)

        async with factory() as session:
            pending = (
                await session.execute(
                    select(func.count())
                    .select_from(MatchCandidate)
                    .where(
                        MatchCandidate.return_order_id == ids["return_id"],
                        MatchCandidate.buyer_id == ids["buyer_id"],
                        MatchCandidate.status == MatchStatus.PENDING,
                    )
                )
            ).scalar_one()
            assert pending == 1

            total = (
                await session.execute(
                    select(func.count()).select_from(MatchCandidate)
                )
            ).scalar_one()
            assert total == 1

            # Active-match count incremented by exactly one (Requirement 6.7).
            assert await get_active_match_count(session) == count_before + 1
    finally:
        await engine.dispose()


@settings(max_examples=10, deadline=None)
@given(
    signal_source=st.sampled_from(SIGNAL_SOURCES),
    lat_off=st.floats(
        min_value=-_MAX_OFFSET_DEG,
        max_value=_MAX_OFFSET_DEG,
        allow_nan=False,
        allow_infinity=False,
    ),
    lon_off=st.floats(
        min_value=-_MAX_OFFSET_DEG,
        max_value=_MAX_OFFSET_DEG,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_match_creation_produces_pending_and_bumps_count(
    signal_source: str, lat_off: float, lon_off: float
) -> None:
    """Property 10: eligible nearby signal -> one PENDING candidate, count +1."""
    asyncio.run(_run_example(signal_source, lat_off, lon_off))
