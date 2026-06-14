"""Property 11 — no duplicate PENDING candidates (task 10.3).

Feature: amazon-edge-return, Property 11: No duplicate PENDING candidates.

For any number N >= 2 of repeated demand signals for the same (buyer, return)
pair, at most one PENDING :class:`MatchCandidate` exists for that pair and the
active-match count is incremented at most once. The duplicate guard
(Requirement 6.9) is what makes re-processing a signal a no-op once a PENDING
candidate already exists.

This property needs a database, so we combine Hypothesis with the in-memory
async SQLite + FakeGateway harness from ``tests/test_matching_engine.py``: a
fresh in-memory engine/sessionmaker is built per generated example inside an
async helper invoked via ``asyncio.run`` so each case is fully isolated.

**Validates: Requirements 6.9**
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
SIGNAL_SOURCES = ("cart", "buynow", "wishlist", "viewed")


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
        await session.commit()
        return {
            "seller_id": seller.id,
            "buyer_id": buyer.id,
            "asin": product.asin,
            "return_id": ret.id,
        }


async def _run_example(repeats: int, sources: list[str]) -> None:
    """Seed a fresh DB, fire N repeated signals, assert the no-duplicate property."""
    factory, engine = await _build_factory()
    try:
        ids = await _seed_scanning_return(factory)

        # Fire N >= 2 signals for the same (buyer, return) pair, each in its own
        # session/transaction (mirrors how repeated HTTP signals would arrive).
        for i in range(repeats):
            async with factory() as session:
                await run_matching_for_signal(
                    session,
                    asin=str(ids["asin"]),
                    buyer_id=int(ids["buyer_id"]),
                    signal_source=sources[i],
                    buyer_lat=RAHUL_LAT,
                    buyer_lon=RAHUL_LON,
                    now=NOW,
                )

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
            # At most one PENDING candidate for the pair (Requirement 6.9).
            assert pending <= 1

            # Active-match count incremented at most once across all repeats.
            assert await get_active_match_count(session) <= 1
    finally:
        await engine.dispose()


@settings(max_examples=10, deadline=None)
@given(data=st.data())
def test_no_duplicate_pending_candidates(data: st.DataObject) -> None:
    """Property 11: N>=2 repeated signals -> <=1 PENDING candidate, count +<=1."""
    repeats = data.draw(st.integers(min_value=2, max_value=6), label="repeats")
    sources = data.draw(
        st.lists(
            st.sampled_from(SIGNAL_SOURCES),
            min_size=repeats,
            max_size=repeats,
        ),
        label="sources",
    )
    asyncio.run(_run_example(repeats, sources))
