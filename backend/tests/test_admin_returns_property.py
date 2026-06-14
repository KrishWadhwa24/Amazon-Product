"""Property 25 — admin returns filter (task 24.2).

Feature: amazon-edge-return, Property 25: Admin returns filter.

For any randomly seeded multiset of ``ReturnOrder`` rows spread across the
``ReturnStatus`` values, and for ``status_param`` equal to ``ALL`` or any
recognized status value (canonical status or the admin aliases CACHED ≡
MICROWAREHOUSE, RTO_QUEUED ≡ EXPIRED, NGO_QUEUED ≡ NGO_ROUTING),
``admin.list_returns`` returns *exactly* the ReturnOrders whose status matches
the requested value — every order when ``ALL`` — each joined with its Product
and seller User, and an empty list when none match.

This property is side-effecting, so it runs against the same in-memory async
SQLite harness used by ``tests/test_admin.py``. Each Hypothesis example builds a
fresh engine/sessionmaker, seeds ``N`` ReturnOrders with random statuses, and
drives the service via ``asyncio.run`` for full per-example isolation. The
expected matching ids are computed independently of the service and compared as
sets.

Validates: Requirements 14.1, 14.2
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
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
from app.models.return_order import ReturnOrder
from app.models.user import User
from app.services import admin as admin_service

# The filter values the admin data table can request: the ALL sentinel, every
# canonical ReturnStatus value, and the three display aliases (Requirement 14.5).
_ALIAS_TO_CANONICAL: dict[str, ReturnStatus] = {
    "CACHED": ReturnStatus.MICROWAREHOUSE,
    "RTO_QUEUED": ReturnStatus.EXPIRED,
    "NGO_QUEUED": ReturnStatus.NGO_ROUTING,
}
_FILTER_VALUES: list[str] = (
    ["ALL"] + [s.value for s in ReturnStatus] + list(_ALIAS_TO_CANONICAL)
)

# A list (0..N) of arbitrary ReturnStatus values is the seeded multiset.
_status_lists = st.lists(st.sampled_from(list(ReturnStatus)), min_size=0, max_size=30)


def _expected_ids(
    seeded: list[tuple[int, ReturnStatus]], status_param: str
) -> set[int]:
    """Independently compute the ids expected to match ``status_param``.

    ``ALL`` selects every seeded id; an alias resolves to its canonical status;
    otherwise the value is a canonical :class:`ReturnStatus`. The expected set is
    every seeded id whose status equals the resolved canonical status.
    """
    if status_param == "ALL":
        return {rid for rid, _ in seeded}
    canonical = _ALIAS_TO_CANONICAL.get(status_param) or ReturnStatus(status_param)
    return {rid for rid, status in seeded if status == canonical}


async def _run_example(*, statuses: list[ReturnStatus], status_param: str) -> None:
    """Seed ``len(statuses)`` returns then assert Property 25 for the filter."""
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

        # (return_order_id, status) for every seeded row.
        seeded: list[tuple[int, ReturnStatus]] = []

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
                ro = ReturnOrder(
                    seller_id=seller.id,
                    product_id=product.id,
                    order_history_id=order.id,
                    asin=product.asin,
                    status=status,
                    initiated_at=now - timedelta(hours=49),
                    expires_at=now - timedelta(hours=1),
                )
                session.add(ro)
                await session.flush()
                seeded.append((ro.id, status))
            await session.commit()

        async with factory() as session:
            rows = await admin_service.list_returns(session, status_param)

        returned_ids = {row.id for row in rows}
        expected = _expected_ids(seeded, status_param)

        # Exactly the matching orders (all when ALL); empty when none match
        # (Requirements 14.1, 14.2).
        assert returned_ids == expected
        # No duplicate rows.
        assert len(rows) == len(returned_ids)
        # Every returned row carries the correct canonical status.
        if status_param != "ALL":
            canonical = (
                _ALIAS_TO_CANONICAL.get(status_param) or ReturnStatus(status_param)
            )
            assert all(row.status == canonical for row in rows)
        # Each returned row is joined with its Product and seller User
        # (Requirement 14.1).
        for row in rows:
            assert row.product is not None
            assert row.product.asin == "B0SONY520"
            assert row.product.image_url.strip() != ""
            assert row.seller is not None
            assert row.seller.name == "Priya Sharma"
    finally:
        await engine.dispose()


@settings(
    max_examples=10,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(statuses=_status_lists, status_param=st.sampled_from(_FILTER_VALUES))
def test_admin_returns_filter(
    statuses: list[ReturnStatus], status_param: str
) -> None:
    """Feature: amazon-edge-return, Property 25: Admin returns filter.

    Validates: Requirements 14.1, 14.2
    """
    asyncio.run(_run_example(statuses=statuses, status_param=status_param))
