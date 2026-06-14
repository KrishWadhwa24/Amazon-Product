"""Tests for the buyer notification feed (task 21.1).

Covers :func:`app.services.notifications.list_pending_for_buyer` and the
``GET /api/notifications`` endpoint against an in-memory async SQLite database
(the pattern from ``tests/test_returns.py``) so no PostgreSQL/Redis server is
required.

Scenarios (Requirements 7.2, 7.3, 8.1, 8.6):

* a PENDING candidate (carbon >= 0.1) on a SCANNING return is returned as one
  enriched item with the headline + money_saved + carbon (Requirements 8.1, 8.2);
* a candidate with carbon < 0.1 omits the carbon field (Requirement 7.3);
* a candidate whose ReturnOrder has left SCANNING is NOT returned
  (Requirement 8.6);
* an anonymous caller gets 401 NO_SESSION.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.security import SESSION_COOKIE_NAME, sign_session
from app.db.base import Base
from app.db.session import get_session
from app.main import create_app
from app.models.enums import MatchStatus, NotificationStatus, ReturnStatus
from app.models.match_candidate import MatchCandidate
from app.models.notification import Notification
from app.models.order_history import OrderHistory
from app.models.product import Product
from app.models.return_order import ReturnOrder
from app.models.user import User
from app.services import notifications as notifications_service

NOW = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)


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
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    yield factory
    await engine.dispose()


async def _seed(factory) -> dict[str, int]:
    """Seed a buyer with three candidates exercising every branch.

    * ``cand_high`` — PENDING, carbon 1.2 kg, on a SCANNING return -> surfaced
      with carbon.
    * ``cand_low`` — PENDING, carbon 0.05 kg, on a SCANNING return -> surfaced
      with carbon omitted (Req 7.3).
    * ``cand_not_scanning`` — PENDING but its return has left SCANNING
      (LOCAL_DELIVERY) -> NOT surfaced (Req 8.6).
    """
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

        # Two distinct SCANNING returns: the partial unique index forbids two
        # PENDING candidates for the same (return, buyer) pair (Req 6.9).
        scanning = ReturnOrder(
            seller_id=seller.id,
            product_id=product.id,
            order_history_id=order.id,
            asin=product.asin,
            status=ReturnStatus.SCANNING,
            initiated_at=NOW - timedelta(hours=1),
            expires_at=NOW + timedelta(hours=47),
        )
        scanning_low = ReturnOrder(
            seller_id=seller.id,
            product_id=product.id,
            order_history_id=order.id,
            asin=product.asin,
            status=ReturnStatus.SCANNING,
            initiated_at=NOW - timedelta(hours=1),
            expires_at=NOW + timedelta(hours=47),
        )
        advanced = ReturnOrder(
            seller_id=seller.id,
            product_id=product.id,
            order_history_id=order.id,
            asin=product.asin,
            status=ReturnStatus.LOCAL_DELIVERY,
            initiated_at=NOW - timedelta(hours=1),
            expires_at=NOW + timedelta(hours=47),
        )
        session.add_all([scanning, scanning_low, advanced])
        await session.flush()

        cand_high = MatchCandidate(
            return_order_id=scanning.id,
            buyer_id=buyer.id,
            status=MatchStatus.PENDING,
            distance_km=5.0,
            signal_source="cart",
            local_discount=Decimal("598.80"),
            delivery_time_saved_hours=24,
            carbon_avoided_kg=1.2,
            created_at=NOW,
        )
        cand_low = MatchCandidate(
            return_order_id=scanning_low.id,
            buyer_id=buyer.id,
            status=MatchStatus.PENDING,
            distance_km=6.0,
            signal_source="wishlist",
            local_discount=Decimal("100.00"),
            delivery_time_saved_hours=12,
            carbon_avoided_kg=0.05,
            created_at=NOW - timedelta(minutes=5),
        )
        cand_not_scanning = MatchCandidate(
            return_order_id=advanced.id,
            buyer_id=buyer.id,
            status=MatchStatus.PENDING,
            distance_km=3.0,
            signal_source="buynow",
            local_discount=Decimal("250.00"),
            delivery_time_saved_hours=18,
            carbon_avoided_kg=0.9,
            created_at=NOW - timedelta(minutes=10),
        )
        session.add_all([cand_high, cand_low, cand_not_scanning])
        await session.flush()

        # PENDING notification rows mirror what the matching engine creates.
        session.add_all(
            [
                Notification(
                    match_candidate_id=cand_high.id,
                    buyer_id=buyer.id,
                    status=NotificationStatus.PENDING,
                    created_at=NOW,
                ),
                Notification(
                    match_candidate_id=cand_low.id,
                    buyer_id=buyer.id,
                    status=NotificationStatus.PENDING,
                    created_at=NOW,
                ),
                Notification(
                    match_candidate_id=cand_not_scanning.id,
                    buyer_id=buyer.id,
                    status=NotificationStatus.PENDING,
                    created_at=NOW,
                ),
            ]
        )
        await session.commit()
        return {
            "buyer_id": buyer.id,
            "seller_id": seller.id,
            "cand_high_id": cand_high.id,
            "cand_low_id": cand_low.id,
            "cand_not_scanning_id": cand_not_scanning.id,
        }


# --------------------------------------------------------------------------- #
# Service: enrichment, carbon suppression, SCANNING-only (Req 7.2, 7.3, 8.6)
# --------------------------------------------------------------------------- #


async def test_list_pending_enriches_and_filters(sessionmaker_fixture) -> None:
    ids = await _seed(sessionmaker_fixture)
    async with sessionmaker_fixture() as session:
        views = await notifications_service.list_pending_for_buyer(
            session, ids["buyer_id"], now=NOW
        )

    by_id = {v.candidate_id: v for v in views}
    # Only the two SCANNING candidates surface; the LOCAL_DELIVERY one does not.
    assert set(by_id) == {ids["cand_high_id"], ids["cand_low_id"]}
    assert ids["cand_not_scanning_id"] not in by_id

    high = by_id[ids["cand_high_id"]]
    assert high.headline == notifications_service.DEAL_HEADLINE
    assert high.money_saved == Decimal("598.80")
    assert high.delivery_time_saved_hours == 24
    assert high.carbon_avoided_kg == 1.2  # >= 0.1 -> present (Req 7.2)
    assert high.product_name == "Sony WH-CH520 Wireless Headphones"
    assert high.product_asin == "B0SONY520"
    assert high.product_image_url == "https://img.example/sony.jpg"

    # Carbon below 0.1 kg is suppressed (Req 7.3).
    low = by_id[ids["cand_low_id"]]
    assert low.carbon_avoided_kg is None


async def test_list_pending_stamps_delivered_at(sessionmaker_fixture) -> None:
    """Serving stamps delivered_at on PENDING notifications, keeping status."""
    ids = await _seed(sessionmaker_fixture)
    async with sessionmaker_fixture() as session:
        await notifications_service.list_pending_for_buyer(
            session, ids["buyer_id"], now=NOW
        )

    async with sessionmaker_fixture() as session:
        rows = (
            await session.execute(
                select(Notification).where(
                    Notification.match_candidate_id.in_(
                        [ids["cand_high_id"], ids["cand_low_id"]]
                    )
                )
            )
        ).scalars().all()
        assert all(n.delivered_at is not None for n in rows)
        # Status preserved as PENDING until accept/reject (Req 8.6).
        assert all(n.status == NotificationStatus.PENDING for n in rows)


# --------------------------------------------------------------------------- #
# Endpoint wiring — GET /api/notifications
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


async def test_endpoint_returns_enriched_items_for_buyer(sessionmaker_fixture) -> None:
    ids = await _seed(sessionmaker_fixture)
    client = _build_client(sessionmaker_fixture)
    client.cookies.set(SESSION_COOKIE_NAME, sign_session(ids["buyer_id"]))

    resp = client.get("/api/notifications")
    assert resp.status_code == 200
    body = resp.json()
    by_id = {item["candidate_id"]: item for item in body}

    assert set(by_id) == {ids["cand_high_id"], ids["cand_low_id"]}

    high = by_id[ids["cand_high_id"]]
    assert high["headline"] == notifications_service.DEAL_HEADLINE
    assert Decimal(str(high["money_saved"])) == Decimal("598.80")
    assert high["delivery_time_saved_hours"] == 24
    assert high["carbon_avoided_kg"] == 1.2
    assert high["product"]["name"] == "Sony WH-CH520 Wireless Headphones"
    assert high["product"]["asin"] == "B0SONY520"
    assert high["product"]["image_url"] == "https://img.example/sony.jpg"

    # Carbon field omitted entirely when suppressed (Req 7.3).
    low = by_id[ids["cand_low_id"]]
    assert "carbon_avoided_kg" not in low


async def test_endpoint_rejects_anonymous_with_401(sessionmaker_fixture) -> None:
    await _seed(sessionmaker_fixture)
    client = _build_client(sessionmaker_fixture)

    resp = client.get("/api/notifications")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "NO_SESSION"


def test_route_registered() -> None:
    """The notifications GET route is registered on the app."""
    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/api/notifications" in paths
