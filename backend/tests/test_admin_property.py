"""Property-based test for admin metric bounds (task 23.2).

Feature: amazon-edge-return, Property 24: Admin metric bounds.

For any system state — any multiset of ``ReturnOrder`` rows spread across the
``ReturnStatus`` values — ``compute_metrics`` must return a Cache Storage
Capacity with ``0 <= cache_used <= cache_total`` and ``cache_total >= 1``, plus
non-negative Reverse Logistics Saved, Carbon Offset Index, and NGO CSR Credits.
``cache_used`` must equal ``min(microwarehouse_count, cache_total)`` (the real
MICROWAREHOUSE count clamped into the mocked capacity).

The test combines Hypothesis with a fresh in-memory async SQLite engine per
example (via :func:`asyncio.run`), mirroring the harness in ``test_admin.py`` so
no PostgreSQL/Redis server is required.

Validates: Requirements 13.1
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.enums import ReturnStatus
from app.models.order_history import OrderHistory
from app.models.product import Product
from app.models.return_order import ReturnOrder
from app.models.user import User
from app.services import admin as admin_service

# A list (0..N) of arbitrary ReturnStatus values describes any system state.
_status_lists = st.lists(st.sampled_from(list(ReturnStatus)), min_size=0, max_size=40)


async def _compute_for_statuses(statuses: list[ReturnStatus]) -> tuple:
    """Seed a fresh in-memory DB with the given returns and compute metrics.

    Returns ``(metrics, microwarehouse_count)`` for assertions.
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

        async with factory() as session:
            metrics = await admin_service.compute_metrics(session)
    finally:
        await engine.dispose()

    microwarehouse_count = sum(1 for s in statuses if s is ReturnStatus.MICROWAREHOUSE)
    return metrics, microwarehouse_count


@settings(max_examples=10, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(statuses=_status_lists)
def test_admin_metric_bounds(statuses: list[ReturnStatus]) -> None:
    """Feature: amazon-edge-return, Property 24: Admin metric bounds.

    Validates: Requirements 13.1
    """
    metrics, microwarehouse_count = asyncio.run(_compute_for_statuses(statuses))

    # Cache Storage Capacity bounds.
    assert metrics.cache_total >= 1
    assert 0 <= metrics.cache_used <= metrics.cache_total
    # cache_used is the real MICROWAREHOUSE count clamped into capacity.
    assert metrics.cache_used == min(microwarehouse_count, metrics.cache_total)

    # Aggregates are non-negative.
    assert metrics.reverse_logistics_saved >= Decimal("0")
    assert metrics.carbon_offset_index_kg >= 0.0
    assert metrics.ngo_csr_credits >= Decimal("0")
