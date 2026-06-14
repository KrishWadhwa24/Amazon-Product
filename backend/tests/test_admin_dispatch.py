"""Tests for admin batch dispatch (task 24.6).

Covers the admin service (``dispatch_rto``) and the
``POST /api/admin/dispatch`` endpoint against an in-memory async SQLite database
so no PostgreSQL/Redis server is required (Requirements 16.1, 16.2, 16.3, 16.4,
16.5).

The admin "RTO_QUEUED" disposition is the display alias for the canonical
``EXPIRED`` status, so dispatch transitions every EXPIRED ReturnOrder to
FC_TRANSIT, returns the transitioned count, and recalculates metrics.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.errors import MissingHubError, UnsupportedActionError
from app.db.base import Base
from app.db.session import get_session
from app.main import create_app
from app.models.enums import ReturnStatus
from app.models.order_history import OrderHistory
from app.models.product import Product
from app.models.return_order import ReturnOrder
from app.models.user import User
from app.services import admin as admin_service
from app.services.admin import DISPATCH_ACTION_BATCH_FC_RTO


@pytest_asyncio.fixture
async def sessionmaker_fixture():
    """Yield an async sessionmaker backed by a shared in-memory SQLite DB."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_returns(factory, statuses: list[ReturnStatus]) -> None:
    """Seed one seller/product/order plus a ReturnOrder per status given."""
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


async def _count_by_status(factory) -> dict[ReturnStatus, int]:
    async with factory() as session:
        result = await session.execute(
            select(ReturnOrder.status, func.count()).group_by(ReturnOrder.status)
        )
        return {status: count for status, count in result.all()}


# --------------------------------------------------------------------------- #
# Service — dispatch_rto
# --------------------------------------------------------------------------- #


async def test_dispatch_transitions_all_expired_to_fc_transit(
    sessionmaker_fixture,
) -> None:
    """Every EXPIRED (RTO_QUEUED) return moves to FC_TRANSIT (Req 16.1)."""
    await _seed_returns(
        sessionmaker_fixture,
        [
            ReturnStatus.EXPIRED,
            ReturnStatus.EXPIRED,
            ReturnStatus.EXPIRED,
            ReturnStatus.SCANNING,
            ReturnStatus.MICROWAREHOUSE,
            ReturnStatus.NGO_ROUTING,
        ],
    )
    async with sessionmaker_fixture() as session:
        result = await admin_service.dispatch_rto(
            session, action=DISPATCH_ACTION_BATCH_FC_RTO, hub_id="IND-BLR-01"
        )

    assert result.transitioned_count == 3

    counts = await _count_by_status(sessionmaker_fixture)
    # All three EXPIRED returns are now FC_TRANSIT; no EXPIRED remain.
    assert counts.get(ReturnStatus.EXPIRED, 0) == 0
    assert counts.get(ReturnStatus.FC_TRANSIT, 0) == 3
    # Unrelated returns are left unchanged (Req 16.1 "transition every RTO_QUEUED").
    assert counts.get(ReturnStatus.SCANNING, 0) == 1
    assert counts.get(ReturnStatus.MICROWAREHOUSE, 0) == 1
    assert counts.get(ReturnStatus.NGO_ROUTING, 0) == 1


async def test_dispatch_returns_recalculated_metrics(sessionmaker_fixture) -> None:
    """A successful dispatch returns the recalculated metric bundle (Req 16.2)."""
    await _seed_returns(
        sessionmaker_fixture,
        [ReturnStatus.EXPIRED, ReturnStatus.MICROWAREHOUSE, ReturnStatus.NGO_ROUTING],
    )
    async with sessionmaker_fixture() as session:
        result = await admin_service.dispatch_rto(
            session, action=DISPATCH_ACTION_BATCH_FC_RTO, hub_id="IND-BLR-01"
        )

    metrics = result.metrics
    # Metric bounds hold post-dispatch (Property 24 / Req 13.1).
    assert metrics.cache_total >= 1
    assert 0 <= metrics.cache_used <= metrics.cache_total
    assert metrics.reverse_logistics_saved >= Decimal("0")
    assert metrics.carbon_offset_index_kg >= 0.0
    assert metrics.ngo_csr_credits >= Decimal("0")
    # Real read: one MICROWAREHOUSE (CACHED) return.
    assert metrics.cache_used == 1


async def test_dispatch_zero_expired_returns_count_zero_no_changes(
    sessionmaker_fixture,
) -> None:
    """No RTO_QUEUED returns -> success, count 0, nothing changes (Req 16.5)."""
    await _seed_returns(
        sessionmaker_fixture,
        [ReturnStatus.SCANNING, ReturnStatus.MICROWAREHOUSE],
    )
    before = await _count_by_status(sessionmaker_fixture)

    async with sessionmaker_fixture() as session:
        result = await admin_service.dispatch_rto(
            session, action=DISPATCH_ACTION_BATCH_FC_RTO, hub_id="IND-BLR-01"
        )

    assert result.transitioned_count == 0
    after = await _count_by_status(sessionmaker_fixture)
    assert before == after  # no status changes


async def test_dispatch_unsupported_action_raises_no_changes(
    sessionmaker_fixture,
) -> None:
    """An unsupported action raises UnsupportedActionError, no changes (Req 16.3)."""
    await _seed_returns(sessionmaker_fixture, [ReturnStatus.EXPIRED, ReturnStatus.EXPIRED])
    before = await _count_by_status(sessionmaker_fixture)

    async with sessionmaker_fixture() as session:
        with pytest.raises(UnsupportedActionError):
            await admin_service.dispatch_rto(
                session, action="NOT_AN_ACTION", hub_id="IND-BLR-01"
            )

    after = await _count_by_status(sessionmaker_fixture)
    assert before == after  # rejection leaves the store untouched


@pytest.mark.parametrize("hub_id", [None, "", "   "])
async def test_dispatch_missing_hub_raises_no_changes(
    sessionmaker_fixture, hub_id
) -> None:
    """An absent/empty/blank hub_id raises MissingHubError, no changes (Req 16.4)."""
    await _seed_returns(sessionmaker_fixture, [ReturnStatus.EXPIRED, ReturnStatus.EXPIRED])
    before = await _count_by_status(sessionmaker_fixture)

    async with sessionmaker_fixture() as session:
        with pytest.raises(MissingHubError):
            await admin_service.dispatch_rto(
                session, action=DISPATCH_ACTION_BATCH_FC_RTO, hub_id=hub_id
            )

    after = await _count_by_status(sessionmaker_fixture)
    assert before == after


# --------------------------------------------------------------------------- #
# Endpoint wiring — POST /api/admin/dispatch
# --------------------------------------------------------------------------- #


def _build_client(factory) -> TestClient:
    """Return a TestClient for an app whose DB session uses the test factory."""
    app = create_app()

    async def _override_get_session():
        async with factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = _override_get_session
    return TestClient(app)


async def test_endpoint_dispatch_success_shape(sessionmaker_fixture) -> None:
    """POST /api/admin/dispatch returns {transitioned_count, metrics} (Req 16.1, 16.2)."""
    await _seed_returns(
        sessionmaker_fixture,
        [ReturnStatus.EXPIRED, ReturnStatus.EXPIRED, ReturnStatus.SCANNING],
    )
    client = _build_client(sessionmaker_fixture)

    resp = client.post(
        "/api/admin/dispatch",
        json={"action": DISPATCH_ACTION_BATCH_FC_RTO, "hub_id": "IND-BLR-01"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"transitioned_count", "metrics"}
    assert body["transitioned_count"] == 2
    assert set(body["metrics"].keys()) == {
        "cache_used",
        "cache_total",
        "reverse_logistics_saved",
        "carbon_offset_index_kg",
        "ngo_csr_credits",
    }

    # The two EXPIRED returns are now FC_TRANSIT.
    counts = await _count_by_status(sessionmaker_fixture)
    assert counts.get(ReturnStatus.FC_TRANSIT, 0) == 2
    assert counts.get(ReturnStatus.EXPIRED, 0) == 0


async def test_endpoint_dispatch_zero_queued_count_zero(sessionmaker_fixture) -> None:
    """No RTO_QUEUED returns -> 200 with transitioned_count 0 (Req 16.5)."""
    await _seed_returns(sessionmaker_fixture, [ReturnStatus.SCANNING])
    client = _build_client(sessionmaker_fixture)

    resp = client.post(
        "/api/admin/dispatch",
        json={"action": DISPATCH_ACTION_BATCH_FC_RTO, "hub_id": "IND-BLR-01"},
    )
    assert resp.status_code == 200
    assert resp.json()["transitioned_count"] == 0


async def test_endpoint_dispatch_unsupported_action_400(sessionmaker_fixture) -> None:
    """An unsupported action yields 400 UNSUPPORTED_ACTION (Req 16.3)."""
    await _seed_returns(sessionmaker_fixture, [ReturnStatus.EXPIRED])
    client = _build_client(sessionmaker_fixture)

    resp = client.post(
        "/api/admin/dispatch",
        json={"action": "BOGUS", "hub_id": "IND-BLR-01"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "UNSUPPORTED_ACTION"

    # No status changes on rejection.
    counts = await _count_by_status(sessionmaker_fixture)
    assert counts.get(ReturnStatus.EXPIRED, 0) == 1


async def test_endpoint_dispatch_missing_hub_400(sessionmaker_fixture) -> None:
    """An empty hub_id yields 400 HUB_REQUIRED (Req 16.4)."""
    await _seed_returns(sessionmaker_fixture, [ReturnStatus.EXPIRED])
    client = _build_client(sessionmaker_fixture)

    resp = client.post(
        "/api/admin/dispatch",
        json={"action": DISPATCH_ACTION_BATCH_FC_RTO, "hub_id": ""},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "HUB_REQUIRED"

    counts = await _count_by_status(sessionmaker_fixture)
    assert counts.get(ReturnStatus.EXPIRED, 0) == 1
