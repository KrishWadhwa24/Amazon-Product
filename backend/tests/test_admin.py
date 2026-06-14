"""Tests for admin operations metrics (task 23.1).

Covers the admin service (``compute_metrics``) and the
``GET /api/admin/metrics`` endpoint against an in-memory async SQLite database
so no PostgreSQL/Redis server is required (Requirements 13.1, 13.3).

The mock-vs-real boundary is asserted: ``cache_used`` is a real read of the
MICROWAREHOUSE (CACHED) return count, while ``cache_total`` and the three
currency/carbon aggregates are mocked plausible non-negative stand-ins.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.errors import InvalidStatusFilterError, StoreUnavailableError
from app.db.base import Base
from app.db.session import get_session
from app.main import create_app
from app.models.enums import ReturnStatus
from app.models.order_history import OrderHistory
from app.models.product import Product
from app.models.return_order import ReturnOrder
from app.models.user import User
from app.services import admin as admin_service
from app.services.admin import MOCK_CACHE_CAPACITY_TOTAL


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


# --------------------------------------------------------------------------- #
# Service — compute_metrics
# --------------------------------------------------------------------------- #


async def test_compute_metrics_cache_used_counts_microwarehouse(
    sessionmaker_fixture,
) -> None:
    """cache_used equals the real count of MICROWAREHOUSE (CACHED) returns."""
    await _seed_returns(
        sessionmaker_fixture,
        [
            ReturnStatus.MICROWAREHOUSE,
            ReturnStatus.MICROWAREHOUSE,
            ReturnStatus.MICROWAREHOUSE,
            ReturnStatus.NGO_ROUTING,
            ReturnStatus.SCANNING,
            ReturnStatus.LOCAL_DELIVERY,
        ],
    )
    async with sessionmaker_fixture() as session:
        metrics = await admin_service.compute_metrics(session)

    # Real read: 3 cached returns.
    assert metrics.cache_used == 3
    # Mocked capacity, >= 1, and used <= total.
    assert metrics.cache_total >= 1
    assert metrics.cache_total == MOCK_CACHE_CAPACITY_TOTAL
    assert 0 <= metrics.cache_used <= metrics.cache_total
    # Mocked aggregates are non-negative.
    assert metrics.reverse_logistics_saved >= Decimal("0")
    assert metrics.carbon_offset_index_kg >= 0.0
    assert metrics.ngo_csr_credits >= Decimal("0")
    # NGO credits scale off the single NGO_ROUTING return (deterministic mock).
    assert metrics.ngo_csr_credits == Decimal("75.00")


async def test_compute_metrics_empty_db_is_all_zero_used_with_valid_bounds(
    sessionmaker_fixture,
) -> None:
    """With no returns, used is 0 and the invariants still hold."""
    async with sessionmaker_fixture() as session:
        metrics = await admin_service.compute_metrics(session)

    assert metrics.cache_used == 0
    assert metrics.cache_total >= 1
    assert metrics.reverse_logistics_saved == Decimal("0.00")
    assert metrics.carbon_offset_index_kg == 0.0
    assert metrics.ngo_csr_credits == Decimal("0.00")


async def test_compute_metrics_clamps_used_to_total(sessionmaker_fixture) -> None:
    """cache_used never exceeds the mocked capacity (clamped)."""
    # Seed more cached returns than the mocked capacity would be tedious; instead
    # verify the clamp directly by monkeypatching the capacity seam to a small N.
    await _seed_returns(
        sessionmaker_fixture,
        [ReturnStatus.MICROWAREHOUSE, ReturnStatus.MICROWAREHOUSE, ReturnStatus.MICROWAREHOUSE],
    )
    original = admin_service.MOCK_CACHE_CAPACITY_TOTAL
    try:
        admin_service.MOCK_CACHE_CAPACITY_TOTAL = 2
        async with sessionmaker_fixture() as session:
            metrics = await admin_service.compute_metrics(session)
        assert metrics.cache_total == 2
        assert metrics.cache_used == 2  # clamped down from 3
        assert metrics.cache_used <= metrics.cache_total
    finally:
        admin_service.MOCK_CACHE_CAPACITY_TOTAL = original


async def test_compute_metrics_store_failure_raises(sessionmaker_fixture) -> None:
    """A store/query failure surfaces as StoreUnavailableError (Req 13.3)."""
    from sqlalchemy.exc import OperationalError

    async with sessionmaker_fixture() as session:
        async def _boom(*_args, **_kwargs):
            raise OperationalError("SELECT", {}, Exception("store down"))

        session.execute = _boom  # type: ignore[assignment]
        with pytest.raises(StoreUnavailableError):
            await admin_service.compute_metrics(session)


# --------------------------------------------------------------------------- #
# Endpoint wiring — GET /api/admin/metrics
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


async def test_endpoint_metrics_returns_json_shape(sessionmaker_fixture) -> None:
    """GET /api/admin/metrics returns the documented JSON shape (Req 13.1)."""
    await _seed_returns(
        sessionmaker_fixture,
        [ReturnStatus.MICROWAREHOUSE, ReturnStatus.NGO_ROUTING, ReturnStatus.LOCAL_DELIVERY],
    )
    client = _build_client(sessionmaker_fixture)

    resp = client.get("/api/admin/metrics")
    assert resp.status_code == 200
    body = resp.json()

    assert set(body.keys()) == {
        "cache_used",
        "cache_total",
        "reverse_logistics_saved",
        "carbon_offset_index_kg",
        "ngo_csr_credits",
    }
    assert body["cache_used"] == 1
    assert body["cache_total"] >= 1
    assert 0 <= body["cache_used"] <= body["cache_total"]
    assert Decimal(str(body["reverse_logistics_saved"])) >= Decimal("0")
    assert body["carbon_offset_index_kg"] >= 0.0
    assert Decimal(str(body["ngo_csr_credits"])) >= Decimal("0")


# --------------------------------------------------------------------------- #
# Service — list_returns (Requirements 14.1, 14.2, 14.3)
# --------------------------------------------------------------------------- #


async def test_list_returns_all_returns_every_row(sessionmaker_fixture) -> None:
    """status=ALL returns every ReturnOrder regardless of status (Req 14.1)."""
    await _seed_returns(
        sessionmaker_fixture,
        [
            ReturnStatus.SCANNING,
            ReturnStatus.SCANNING,
            ReturnStatus.MICROWAREHOUSE,
            ReturnStatus.NGO_ROUTING,
            ReturnStatus.EXPIRED,
        ],
    )
    async with sessionmaker_fixture() as session:
        rows = await admin_service.list_returns(session, "ALL")

    assert len(rows) == 5
    # Product and seller are eagerly loaded for the table columns (Req 14.1).
    for row in rows:
        assert row.product.asin == "B0SONY520"
        assert row.seller.name == "Priya Sharma"


async def test_list_returns_filters_by_recognized_status(sessionmaker_fixture) -> None:
    """status=SCANNING returns only SCANNING rows (Requirement 14.1)."""
    await _seed_returns(
        sessionmaker_fixture,
        [
            ReturnStatus.SCANNING,
            ReturnStatus.SCANNING,
            ReturnStatus.MICROWAREHOUSE,
            ReturnStatus.NGO_ROUTING,
        ],
    )
    async with sessionmaker_fixture() as session:
        rows = await admin_service.list_returns(session, "SCANNING")

    assert len(rows) == 2
    assert all(r.status == ReturnStatus.SCANNING for r in rows)


async def test_list_returns_alias_cached_maps_to_microwarehouse(
    sessionmaker_fixture,
) -> None:
    """The CACHED alias resolves to MICROWAREHOUSE (Requirement 14.5)."""
    await _seed_returns(
        sessionmaker_fixture,
        [
            ReturnStatus.MICROWAREHOUSE,
            ReturnStatus.MICROWAREHOUSE,
            ReturnStatus.SCANNING,
        ],
    )
    async with sessionmaker_fixture() as session:
        rows = await admin_service.list_returns(session, "CACHED")

    assert len(rows) == 2
    assert all(r.status == ReturnStatus.MICROWAREHOUSE for r in rows)


async def test_list_returns_aliases_rto_and_ngo(sessionmaker_fixture) -> None:
    """RTO_QUEUED≡EXPIRED and NGO_QUEUED≡NGO_ROUTING (Requirement 14.5)."""
    await _seed_returns(
        sessionmaker_fixture,
        [ReturnStatus.EXPIRED, ReturnStatus.NGO_ROUTING, ReturnStatus.SCANNING],
    )
    async with sessionmaker_fixture() as session:
        rto = await admin_service.list_returns(session, "RTO_QUEUED")
        ngo = await admin_service.list_returns(session, "NGO_QUEUED")

    assert [r.status for r in rto] == [ReturnStatus.EXPIRED]
    assert [r.status for r in ngo] == [ReturnStatus.NGO_ROUTING]


async def test_list_returns_no_match_is_empty(sessionmaker_fixture) -> None:
    """A recognized status with no matching rows returns [] (Requirement 14.2)."""
    await _seed_returns(sessionmaker_fixture, [ReturnStatus.SCANNING])
    async with sessionmaker_fixture() as session:
        rows = await admin_service.list_returns(session, "MICROWAREHOUSE")
    assert rows == []


async def test_list_returns_unknown_status_raises(sessionmaker_fixture) -> None:
    """An unrecognized status raises InvalidStatusFilterError (Req 14.3)."""
    await _seed_returns(sessionmaker_fixture, [ReturnStatus.SCANNING])
    async with sessionmaker_fixture() as session:
        with pytest.raises(InvalidStatusFilterError):
            await admin_service.list_returns(session, "NOT_A_STATUS")


# --------------------------------------------------------------------------- #
# Endpoint wiring — GET /api/admin/returns
# --------------------------------------------------------------------------- #


async def test_endpoint_returns_all_shape(sessionmaker_fixture) -> None:
    """GET /api/admin/returns?status=ALL returns all rows with the documented shape."""
    await _seed_returns(
        sessionmaker_fixture,
        [ReturnStatus.SCANNING, ReturnStatus.MICROWAREHOUSE],
    )
    client = _build_client(sessionmaker_fixture)

    resp = client.get("/api/admin/returns", params={"status": "ALL"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2

    row = body[0]
    assert set(row.keys()) == {
        "id",
        "status",
        "asin",
        "product",
        "source",
        "initiated_at",
        "expires_at",
    }
    assert set(row["product"].keys()) == {"name", "image_url", "uploaded_image_path"}
    assert set(row["source"].keys()) == {"user_name", "latitude", "longitude"}
    assert row["asin"] == "B0SONY520"
    assert row["source"]["user_name"] == "Priya Sharma"


async def test_endpoint_returns_filters_scanning(sessionmaker_fixture) -> None:
    """?status=SCANNING returns only scanning rows (Requirement 14.1)."""
    await _seed_returns(
        sessionmaker_fixture,
        [ReturnStatus.SCANNING, ReturnStatus.MICROWAREHOUSE, ReturnStatus.SCANNING],
    )
    client = _build_client(sessionmaker_fixture)

    resp = client.get("/api/admin/returns", params={"status": "SCANNING"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert all(r["status"] == "SCANNING" for r in body)


async def test_endpoint_returns_alias_cached(sessionmaker_fixture) -> None:
    """?status=CACHED maps to MICROWAREHOUSE rows (Requirement 14.5)."""
    await _seed_returns(
        sessionmaker_fixture,
        [ReturnStatus.MICROWAREHOUSE, ReturnStatus.SCANNING],
    )
    client = _build_client(sessionmaker_fixture)

    resp = client.get("/api/admin/returns", params={"status": "CACHED"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["status"] == "MICROWAREHOUSE"


async def test_endpoint_returns_no_match_empty_array(sessionmaker_fixture) -> None:
    """A status with no matching rows returns [] (Requirement 14.2)."""
    await _seed_returns(sessionmaker_fixture, [ReturnStatus.SCANNING])
    client = _build_client(sessionmaker_fixture)

    resp = client.get("/api/admin/returns", params={"status": "NGO_QUEUED"})
    assert resp.status_code == 200
    assert resp.json() == []


async def test_endpoint_returns_unknown_status_400(sessionmaker_fixture) -> None:
    """An unrecognized status yields 400 INVALID_STATUS (Requirement 14.3)."""
    await _seed_returns(sessionmaker_fixture, [ReturnStatus.SCANNING])
    client = _build_client(sessionmaker_fixture)

    resp = client.get("/api/admin/returns", params={"status": "BOGUS"})
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "INVALID_STATUS"
