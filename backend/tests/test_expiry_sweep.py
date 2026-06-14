"""Tests for the expiry sweep and lifecycle transition endpoint (task 8.4).

Covers :func:`app.services.expiry_sweep.run_expiry_sweep_once` and the
``POST /api/returns/{id}/transition`` endpoint, both against an in-memory async
SQLite database (the pattern from ``tests/test_returns.py``) so no
PostgreSQL/Redis server is required (Requirements 3.4, 3.5, 9.4, 10.5, 10.7).
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

from app.db.base import Base
from app.db.session import get_session
from app.main import create_app
from app.models.enums import MatchStatus, ReturnStatus
from app.models.match_candidate import MatchCandidate
from app.models.order_history import OrderHistory
from app.models.product import Product
from app.models.return_order import ReturnOrder
from app.models.user import User
from app.services.expiry_sweep import run_expiry_sweep_once

# Routing thresholds: threshold = est_reverse_logistics_cost + ₹150.
# NGO product: price (300) <= 200 + 150 = 350 -> NGO_ROUTING.
# Microwarehouse product: price (5000) > 200 + 150 = 350 -> MICROWAREHOUSE.


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


async def _seed(factory) -> dict[str, int]:
    """Seed a seller, a buyer, two products (NGO-bound and cache-bound), orders."""
    async with factory() as session:
        seller = User(
            name="Priya Sharma",
            email="priya@example.com",
            password_hash="x",
            latitude=12.9781,
            longitude=77.6389,
        )
        buyer = User(
            name="Rahul Verma",
            email="rahul@example.com",
            password_hash="x",
            latitude=12.9352,
            longitude=77.6271,
        )
        ngo_product = Product(
            asin="B0CHEAP01",
            name="Cheap Item",
            price=Decimal("300.00"),  # <= 350 threshold -> NGO_ROUTING
            rating=4.0,
            review_count=10,
            image_url="https://img.example/cheap.jpg",
            estimated_reverse_logistics_cost=Decimal("200.00"),
        )
        cache_product = Product(
            asin="B0PRICEY1",
            name="Pricey Item",
            price=Decimal("5000.00"),  # > 350 threshold -> MICROWAREHOUSE
            rating=4.8,
            review_count=42,
            image_url="https://img.example/pricey.jpg",
            estimated_reverse_logistics_cost=Decimal("200.00"),
        )
        session.add_all([seller, buyer, ngo_product, cache_product])
        await session.flush()
        ngo_order = OrderHistory(
            user_id=seller.id,
            product_id=ngo_product.id,
            purchased_at=datetime.now(timezone.utc) - timedelta(days=3),
        )
        cache_order = OrderHistory(
            user_id=seller.id,
            product_id=cache_product.id,
            purchased_at=datetime.now(timezone.utc) - timedelta(days=3),
        )
        session.add_all([ngo_order, cache_order])
        await session.commit()
        return {
            "seller_id": seller.id,
            "buyer_id": buyer.id,
            "ngo_product_id": ngo_product.id,
            "cache_product_id": cache_product.id,
            "ngo_order_id": ngo_order.id,
            "cache_order_id": cache_order.id,
            "ngo_asin": ngo_product.asin,
            "cache_asin": cache_product.asin,
        }


def _make_return(ids: dict[str, int], *, product: str, status: ReturnStatus, expires_at: datetime) -> ReturnOrder:
    """Build a ReturnOrder for the named seeded product ('ngo' or 'cache')."""
    return ReturnOrder(
        seller_id=ids["seller_id"],
        product_id=ids[f"{product}_product_id"],
        order_history_id=ids[f"{product}_order_id"],
        asin=ids[f"{product}_asin"],
        status=status,
        initiated_at=expires_at - timedelta(seconds=172_800),
        expires_at=expires_at,
    )


# --------------------------------------------------------------------------- #
# run_expiry_sweep_once core (Requirements 3.4, 3.5, 9.4, 10.9-10.12)
# --------------------------------------------------------------------------- #


async def test_sweep_expires_and_routes_to_ngo_with_pending_candidates_expired(
    sessionmaker_fixture,
) -> None:
    """A due, unmatched SCANNING return becomes EXPIRED->routed; PENDING->EXPIRED."""
    ids = await _seed(sessionmaker_fixture)
    now = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    async with sessionmaker_fixture() as session:
        ret = _make_return(
            ids, product="ngo", status=ReturnStatus.SCANNING,
            expires_at=now - timedelta(seconds=1),
        )
        session.add(ret)
        await session.flush()
        pending = MatchCandidate(
            return_order_id=ret.id,
            buyer_id=ids["buyer_id"],
            status=MatchStatus.PENDING,
            distance_km=3.21,
            signal_source="cart",
            created_at=now - timedelta(hours=1),
        )
        session.add(pending)
        await session.commit()
        ret_id = ret.id
        pending_id = pending.id

    async with sessionmaker_fixture() as session:
        swept = await run_expiry_sweep_once(session, now=now)
        assert swept == [ret_id]

    async with sessionmaker_fixture() as session:
        refreshed = await session.get(ReturnOrder, ret_id)
        # Routed away from SCANNING to the NGO terminal state (price <= threshold).
        assert refreshed.status == ReturnStatus.NGO_ROUTING
        assert refreshed.reverse_transit_threshold == Decimal("350.00")
        cand = await session.get(MatchCandidate, pending_id)
        assert cand.status == MatchStatus.EXPIRED


async def test_sweep_routes_expensive_item_to_microwarehouse(
    sessionmaker_fixture,
) -> None:
    """A due return whose price exceeds the threshold routes to MICROWAREHOUSE."""
    ids = await _seed(sessionmaker_fixture)
    now = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    async with sessionmaker_fixture() as session:
        ret = _make_return(
            ids, product="cache", status=ReturnStatus.SCANNING,
            expires_at=now,  # expires_at <= now is due
        )
        session.add(ret)
        await session.commit()
        ret_id = ret.id

    async with sessionmaker_fixture() as session:
        swept = await run_expiry_sweep_once(session, now=now)
        assert swept == [ret_id]

    async with sessionmaker_fixture() as session:
        refreshed = await session.get(ReturnOrder, ret_id)
        assert refreshed.status == ReturnStatus.MICROWAREHOUSE


async def test_sweep_skips_not_yet_expired_scanning(sessionmaker_fixture) -> None:
    """A SCANNING return whose window is still open is left untouched."""
    ids = await _seed(sessionmaker_fixture)
    now = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    async with sessionmaker_fixture() as session:
        ret = _make_return(
            ids, product="ngo", status=ReturnStatus.SCANNING,
            expires_at=now + timedelta(hours=1),
        )
        session.add(ret)
        await session.commit()
        ret_id = ret.id

    async with sessionmaker_fixture() as session:
        swept = await run_expiry_sweep_once(session, now=now)
        assert swept == []
        refreshed = await session.get(ReturnOrder, ret_id)
        assert refreshed.status == ReturnStatus.SCANNING


async def test_sweep_skips_due_return_with_accepted_candidate(
    sessionmaker_fixture,
) -> None:
    """A due return that already has an ACCEPTED candidate is not expired."""
    ids = await _seed(sessionmaker_fixture)
    now = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    async with sessionmaker_fixture() as session:
        ret = _make_return(
            ids, product="ngo", status=ReturnStatus.SCANNING,
            expires_at=now - timedelta(seconds=10),
        )
        session.add(ret)
        await session.flush()
        accepted = MatchCandidate(
            return_order_id=ret.id,
            buyer_id=ids["buyer_id"],
            status=MatchStatus.ACCEPTED,
            distance_km=1.0,
            signal_source="cart",
            created_at=now - timedelta(hours=2),
        )
        session.add(accepted)
        await session.commit()
        ret_id = ret.id

    async with sessionmaker_fixture() as session:
        swept = await run_expiry_sweep_once(session, now=now)
        assert swept == []
        refreshed = await session.get(ReturnOrder, ret_id)
        assert refreshed.status == ReturnStatus.SCANNING


# --------------------------------------------------------------------------- #
# Endpoint wiring — POST /api/returns/{id}/transition (Requirements 10.5, 10.7)
# --------------------------------------------------------------------------- #


def _build_client(factory) -> TestClient:
    """Return a TestClient whose DB session uses the test factory."""
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


async def _make_scanning_return(factory, ids: dict[str, int]) -> int:
    async with factory() as session:
        ret = _make_return(
            ids, product="ngo", status=ReturnStatus.SCANNING,
            expires_at=datetime(2024, 6, 1, tzinfo=timezone.utc) + timedelta(hours=10),
        )
        session.add(ret)
        await session.commit()
        return ret.id


async def test_transition_endpoint_valid_returns_new_status(
    sessionmaker_fixture,
) -> None:
    """A legal SCANNING->MATCH_FOUND transition persists and returns {id,status}."""
    ids = await _seed(sessionmaker_fixture)
    ret_id = await _make_scanning_return(sessionmaker_fixture, ids)
    client = _build_client(sessionmaker_fixture)

    resp = client.post(
        f"/api/returns/{ret_id}/transition", json={"target_status": "MATCH_FOUND"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"id": ret_id, "status": "MATCH_FOUND"}

    async with sessionmaker_fixture() as session:
        refreshed = await session.get(ReturnOrder, ret_id)
        assert refreshed.status == ReturnStatus.MATCH_FOUND


async def test_transition_endpoint_invalid_returns_409_unchanged(
    sessionmaker_fixture,
) -> None:
    """An undefined transition yields 409 INVALID_TRANSITION; status unchanged."""
    ids = await _seed(sessionmaker_fixture)
    ret_id = await _make_scanning_return(sessionmaker_fixture, ids)
    client = _build_client(sessionmaker_fixture)

    resp = client.post(
        f"/api/returns/{ret_id}/transition", json={"target_status": "LOCAL_DELIVERY"}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "INVALID_TRANSITION"

    async with sessionmaker_fixture() as session:
        refreshed = await session.get(ReturnOrder, ret_id)
        assert refreshed.status == ReturnStatus.SCANNING


async def test_transition_endpoint_unknown_id_returns_404(
    sessionmaker_fixture,
) -> None:
    """An unknown ReturnOrder id yields 404."""
    await _seed(sessionmaker_fixture)
    client = _build_client(sessionmaker_fixture)

    resp = client.post(
        "/api/returns/999999/transition", json={"target_status": "MATCH_FOUND"}
    )
    assert resp.status_code == 404
