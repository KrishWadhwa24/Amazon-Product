"""Property 18 — leaving SCANNING expires outstanding PENDING candidates
(task 11.4).

Feature: amazon-edge-return, Property 18: Leaving SCANNING expires outstanding
PENDING candidates.

For a return with ``K`` (``K >= 1``) PENDING candidates for distinct buyers,
accepting one buyer's candidate leaves that one ``ACCEPTED`` and every OTHER
PENDING candidate for the same return ``EXPIRED`` — because accepting advances
the return out of SCANNING.

This property is side-effecting, so it runs against the same in-memory async
SQLite harness used by ``tests/test_matches.py``. Each Hypothesis example builds
a fresh engine/sessionmaker, seeds a SCANNING return with ``K`` distinct-buyer
PENDING candidates, accepts one (varying which), and drives the service via
``asyncio.run`` for full per-example isolation.

Validates: Requirements 9.4, 9.8
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

PRIYA_LAT, PRIYA_LON = 12.9781, 77.6389

NOW = datetime(2024, 6, 1, 0, 0, 0)

SIGNAL_SOURCES = ("cart", "buynow", "wishlist", "viewed")


async def _run_example(*, k: int, accept_index: int) -> None:
    """Seed a SCANNING return with K distinct-buyer PENDING candidates and
    assert Property 18 after accepting the candidate at ``accept_index``."""
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
            product = Product(
                asin="B0SONY520",
                name="Sony WH-CH520 Wireless Headphones",
                price=Decimal("4990.00"),
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

            # K distinct buyers, each with one PENDING candidate for the return.
            cand_ids: list[int] = []
            for i in range(k):
                buyer = User(
                    name=f"Buyer {i}",
                    email=f"buyer{i}@example.com",
                    password_hash="x",
                    latitude=PRIYA_LAT + 0.001 * i,
                    longitude=PRIYA_LON + 0.001 * i,
                )
                session.add(buyer)
                await session.flush()
                cand = MatchCandidate(
                    return_order_id=ret.id,
                    buyer_id=buyer.id,
                    status=MatchStatus.PENDING,
                    distance_km=1.0 + i,
                    signal_source=SIGNAL_SOURCES[i % len(SIGNAL_SOURCES)],
                    local_discount=Decimal("100.00"),
                    delivery_time_saved_hours=12,
                    carbon_avoided_kg=1.0,
                    created_at=NOW,
                )
                session.add(cand)
                await session.flush()
                cand_ids.append(cand.id)
            await session.commit()
            return_id = ret.id

        accepted_id = cand_ids[accept_index]

        async with factory() as session:
            stmt = (
                select(MatchCandidate)
                .where(MatchCandidate.id == accepted_id)
                .options(selectinload(MatchCandidate.return_order))
            )
            candidate = (await session.execute(stmt)).scalar_one()
            result = await matches_service.accept_match(
                session, candidate, user_id=candidate.buyer_id
            )
            assert result.status == MatchStatus.ACCEPTED

        # The accepted candidate is ACCEPTED; every OTHER is EXPIRED (Req 9.4, 9.8).
        async with factory() as session:
            for cid in cand_ids:
                persisted = await session.get(MatchCandidate, cid)
                if cid == accepted_id:
                    assert persisted.status == MatchStatus.ACCEPTED
                else:
                    assert persisted.status == MatchStatus.EXPIRED
            # No PENDING candidate remains for the return.
            remaining_pending = (
                await session.execute(
                    select(MatchCandidate).where(
                        MatchCandidate.return_order_id == return_id,
                        MatchCandidate.status == MatchStatus.PENDING,
                    )
                )
            ).scalars().all()
            assert remaining_pending == []
    finally:
        await engine.dispose()


@settings(max_examples=10, deadline=None)
@given(data=st.data(), k=st.integers(min_value=1, max_value=6))
def test_leaving_scanning_expires_outstanding_pending(data, k: int) -> None:
    """Feature: amazon-edge-return, Property 18: Leaving SCANNING expires outstanding PENDING candidates.

    Validates: Requirements 9.4, 9.8
    """
    accept_index = data.draw(st.integers(min_value=0, max_value=k - 1))
    asyncio.run(_run_example(k=k, accept_index=accept_index))
