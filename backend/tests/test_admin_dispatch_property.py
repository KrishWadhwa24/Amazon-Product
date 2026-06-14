"""Property-based test for admin batch dispatch (task 24.7).

Feature: amazon-edge-return, Property 26: Batch dispatch transitions all
RTO_QUEUED returns.

For any seeded multiset of ReturnOrders spread across the lifecycle statuses, a
dispatch with a supported action and a non-empty hub identifier transitions
exactly those with status EXPIRED (the admin RTO_QUEUED alias) to FC_TRANSIT,
leaves every other return unchanged, returns ``transitioned_count`` equal to the
prior number of EXPIRED returns (zero when none), and returns recalculated
metrics that satisfy the metric bounds (``cache_total >= 1``,
``0 <= cache_used <= cache_total``, non-negative aggregates).

``dispatch_rto`` persists status changes, so the property is exercised against
the same in-memory async SQLite harness used by ``tests/test_admin_dispatch.py``.
Each Hypothesis example builds and seeds a fresh database and drives the service
via ``asyncio.run``; using a per-example engine avoids sharing function-scoped
async fixtures across Hypothesis examples.

Validates: Requirements 16.1, 16.2, 16.5
"""

from __future__ import annotations

import asyncio
from collections import Counter
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

from app.db.base import Base
from app.models.enums import ReturnStatus
from app.models.order_history import OrderHistory
from app.models.product import Product
from app.models.return_order import ReturnOrder
from app.models.user import User
from app.services import admin as admin_service
from app.services.admin import DISPATCH_ACTION_BATCH_FC_RTO


# --------------------------------------------------------------------------- #
# Hypothesis strategy — a random multiset of lifecycle statuses to seed.
# --------------------------------------------------------------------------- #

# Draw from every lifecycle state so the property covers EXPIRED (the dispatch
# target), the FC_TRANSIT destination (already-present rows must be preserved),
# and every unrelated status. An empty list is allowed so the "zero queued"
# branch (Requirement 16.5) is exercised.
status_list_strategy = st.lists(
    st.sampled_from(list(ReturnStatus)),
    min_size=0,
    max_size=20,
)


async def _count_by_status(factory) -> dict[ReturnStatus, int]:
    """Return the current per-status ReturnOrder counts."""
    async with factory() as session:
        result = await session.execute(
            select(ReturnOrder.status, func.count()).group_by(ReturnOrder.status)
        )
        return {status: count for status, count in result.all()}


async def _run_property(statuses: list[ReturnStatus]) -> None:
    """Seed a fresh DB with `statuses`, dispatch, and assert Property 26."""
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

        # Seed one seller/product/order plus a ReturnOrder per generated status.
        async with factory() as session:
            seller = User(
                name="Seller",
                email="seller@example.com",
                password_hash="x",
                latitude=12.9781,
                longitude=77.6389,
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
                purchased_at=datetime.now(timezone.utc) - timedelta(days=30),
            )
            session.add(order)
            await session.flush()

            now = datetime.now(timezone.utc)
            for status in statuses:
                session.add(
                    ReturnOrder(
                        seller_id=seller.id,
                        product_id=product.id,
                        order_history_id=order.id,
                        asin=product.asin,
                        status=status,
                        initiated_at=now - timedelta(hours=49),
                        expires_at=now - timedelta(hours=1),
                    )
                )
            await session.commit()

        # Record the per-status counts before dispatch.
        before = Counter(statuses)
        prior_expired = before.get(ReturnStatus.EXPIRED, 0)

        # Exercise the system under test.
        async with factory() as session:
            result = await admin_service.dispatch_rto(
                session,
                action=DISPATCH_ACTION_BATCH_FC_RTO,
                hub_id="IND-BLR-01",
            )

        # transitioned_count == prior number of EXPIRED (RTO_QUEUED) returns.
        assert result.transitioned_count == prior_expired

        after = await _count_by_status(factory)

        # No EXPIRED returns remain; FC_TRANSIT grew by exactly the count moved.
        assert after.get(ReturnStatus.EXPIRED, 0) == 0
        expected_fc_transit = before.get(ReturnStatus.FC_TRANSIT, 0) + prior_expired
        assert after.get(ReturnStatus.FC_TRANSIT, 0) == expected_fc_transit

        # Every other status is left unchanged.
        for status in ReturnStatus:
            if status in (ReturnStatus.EXPIRED, ReturnStatus.FC_TRANSIT):
                continue
            assert after.get(status, 0) == before.get(status, 0)

        # The recalculated metrics satisfy the metric bounds (Requirement 16.2).
        metrics = result.metrics
        assert metrics.cache_total >= 1
        assert 0 <= metrics.cache_used <= metrics.cache_total
        assert metrics.reverse_logistics_saved >= Decimal("0")
        assert metrics.carbon_offset_index_kg >= 0.0
        assert metrics.ngo_csr_credits >= Decimal("0")
    finally:
        await engine.dispose()


@settings(max_examples=10, deadline=None)
@given(statuses=status_list_strategy)
def test_batch_dispatch_transitions_all_rto_queued(
    statuses: list[ReturnStatus],
) -> None:
    """Feature: amazon-edge-return, Property 26: Batch dispatch transitions all RTO_QUEUED returns.

    Validates: Requirements 16.1, 16.2, 16.5
    """
    asyncio.run(_run_property(statuses))
