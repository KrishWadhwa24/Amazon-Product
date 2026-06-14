"""Tests for resale listing creation (task 17.1).

Covers the resale service (``create_listing``) and the ``POST /api/resale/list``
endpoint wiring against an in-memory async SQLite database so no
PostgreSQL/Redis server is required (Requirements 11.2, 11.3, 11.4, 11.6, 11.7).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.errors import (
    ForbiddenError,
    InvalidResalePriceError,
    MissingImageError,
    StoreUnavailableError,
    UnsupportedGradeError,
)
from app.core.security import SESSION_COOKIE_NAME, sign_session
from app.db.base import Base
from app.db.session import get_session
from app.main import create_app
from app.models.enums import ConditionGrade, ResaleStatus
from app.models.order_history import OrderHistory
from app.models.product import Product
from app.models.resale_listing import ResaleListing
from app.models.user import User
from app.services import resale as resale_service


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


async def _seed(factory) -> dict[str, object]:
    """Seed two users, a product, and an order in seller's history."""
    async with factory() as session:
        seller = User(
            name="Priya Sharma",
            email="priya@example.com",
            password_hash="x",
            latitude=12.9781,
            longitude=77.6389,
        )
        other = User(
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
        session.add_all([seller, other, product])
        await session.flush()
        order = OrderHistory(
            user_id=seller.id,
            product_id=product.id,
            purchased_at=datetime.now(timezone.utc) - timedelta(days=30),
        )
        session.add(order)
        await session.commit()
        return {
            "seller_id": seller.id,
            "other_user_id": other.id,
            "product_id": product.id,
            "order_history_id": order.id,
            "product_price": product.price,
        }


def _count_listings():
    from sqlalchemy import func, select

    return select(func.count()).select_from(ResaleListing)


# --------------------------------------------------------------------------- #
# Resale service — create_listing (Requirements 11.2, 11.3, 11.4, 11.6, 11.7)
# --------------------------------------------------------------------------- #


async def test_create_listing_creates_active_with_image_and_grade(
    sessionmaker_fixture,
) -> None:
    """A valid request creates an ACTIVE listing carrying the image url."""
    ids = await _seed(sessionmaker_fixture)
    fixed_now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    async with sessionmaker_fixture() as session:
        listing = await resale_service.create_listing(
            session,
            seller_id=ids["seller_id"],
            order_history_id=ids["order_history_id"],
            condition_grade="Good",
            condition_image_url="https://img.example/live-condition.jpg",
            resale_price=Decimal("3000.00"),
            now=fixed_now,
        )
        assert listing.status == ResaleStatus.ACTIVE
        assert listing.condition_grade == ConditionGrade.GOOD
        assert listing.condition_image_url == "https://img.example/live-condition.jpg"
        assert listing.resale_price == Decimal("3000.00")
        assert listing.seller_id == ids["seller_id"]
        assert listing.listed_at.replace(tzinfo=None) == fixed_now.replace(tzinfo=None)


async def test_create_listing_unsupported_grade_raises(sessionmaker_fixture) -> None:
    """A grade outside the accepted set -> UnsupportedGradeError, no listing."""
    ids = await _seed(sessionmaker_fixture)
    async with sessionmaker_fixture() as session:
        with pytest.raises(UnsupportedGradeError):
            await resale_service.create_listing(
                session,
                seller_id=ids["seller_id"],
                order_history_id=ids["order_history_id"],
                condition_grade="Excellent",
                condition_image_url="https://img.example/live.jpg",
                resale_price=Decimal("3000.00"),
            )
        assert (await session.execute(_count_listings())).scalar_one() == 0


async def test_create_listing_empty_image_raises(sessionmaker_fixture) -> None:
    """Empty/whitespace condition_image_url -> MissingImageError, no listing."""
    ids = await _seed(sessionmaker_fixture)
    async with sessionmaker_fixture() as session:
        with pytest.raises(MissingImageError):
            await resale_service.create_listing(
                session,
                seller_id=ids["seller_id"],
                order_history_id=ids["order_history_id"],
                condition_grade="Good",
                condition_image_url="   ",
                resale_price=Decimal("3000.00"),
            )
        assert (await session.execute(_count_listings())).scalar_one() == 0


async def test_create_listing_price_over_ceiling_raises(sessionmaker_fixture) -> None:
    """resale_price greater than product price -> InvalidResalePriceError."""
    ids = await _seed(sessionmaker_fixture)
    async with sessionmaker_fixture() as session:
        with pytest.raises(InvalidResalePriceError):
            await resale_service.create_listing(
                session,
                seller_id=ids["seller_id"],
                order_history_id=ids["order_history_id"],
                condition_grade="Fair",
                condition_image_url="https://img.example/live.jpg",
                resale_price=Decimal("9999.00"),
            )
        assert (await session.execute(_count_listings())).scalar_one() == 0


async def test_create_listing_for_other_users_order_raises_forbidden(
    sessionmaker_fixture,
) -> None:
    """Order not in the seller's history -> ForbiddenError, no listing."""
    ids = await _seed(sessionmaker_fixture)
    async with sessionmaker_fixture() as session:
        with pytest.raises(ForbiddenError):
            await resale_service.create_listing(
                session,
                seller_id=ids["other_user_id"],
                order_history_id=ids["order_history_id"],
                condition_grade="Good",
                condition_image_url="https://img.example/live.jpg",
                resale_price=Decimal("3000.00"),
            )
        assert (await session.execute(_count_listings())).scalar_one() == 0


# --------------------------------------------------------------------------- #
# Endpoint wiring — POST /api/resale/list
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


async def test_endpoint_create_listing_returns_201(sessionmaker_fixture) -> None:
    """Authenticated owner gets 201 and an ACTIVE resale_listing payload."""
    ids = await _seed(sessionmaker_fixture)
    client = _build_client(sessionmaker_fixture)
    client.cookies.set(SESSION_COOKIE_NAME, sign_session(ids["seller_id"]))

    resp = client.post(
        "/api/resale/list",
        json={
            "order_history_id": ids["order_history_id"],
            "condition_grade": "Like New",
            "condition_image_url": "https://img.example/live.jpg",
            "resale_price": "2500.00",
        },
    )
    assert resp.status_code == 201
    body = resp.json()["resale_listing"]
    assert body["status"] == "ACTIVE"
    assert body["condition_grade"] == "Like New"
    assert body["condition_image_url"] == "https://img.example/live.jpg"
    assert body["seller_id"] == ids["seller_id"]


async def test_endpoint_create_listing_unsupported_grade_422(
    sessionmaker_fixture,
) -> None:
    """An unsupported grade -> 422 UNSUPPORTED_GRADE envelope (Req 11.4)."""
    ids = await _seed(sessionmaker_fixture)
    client = _build_client(sessionmaker_fixture)
    client.cookies.set(SESSION_COOKIE_NAME, sign_session(ids["seller_id"]))

    resp = client.post(
        "/api/resale/list",
        json={
            "order_history_id": ids["order_history_id"],
            "condition_grade": "Mint",
            "condition_image_url": "https://img.example/live.jpg",
            "resale_price": "2500.00",
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "UNSUPPORTED_GRADE"


async def test_endpoint_create_listing_empty_image_422(sessionmaker_fixture) -> None:
    """Empty condition_image_url -> 422 CONDITION_IMAGE_REQUIRED (Req 11.7)."""
    ids = await _seed(sessionmaker_fixture)
    client = _build_client(sessionmaker_fixture)
    client.cookies.set(SESSION_COOKIE_NAME, sign_session(ids["seller_id"]))

    resp = client.post(
        "/api/resale/list",
        json={
            "order_history_id": ids["order_history_id"],
            "condition_grade": "Good",
            "condition_image_url": "",
            "resale_price": "2500.00",
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "CONDITION_IMAGE_REQUIRED"


# --------------------------------------------------------------------------- #
# Resale feed — list_active_feed + GET /api/resale/feed
# (Requirements 12.1, 12.2, 12.3, 12.7) — task 18.1
# --------------------------------------------------------------------------- #


async def _seed_feed(factory) -> dict[str, object]:
    """Seed a seller, two products, and 3 listings: 2 ACTIVE + 1 non-active.

    Returns the ids and the expected newest-first order of the ACTIVE listings.
    """
    async with factory() as session:
        seller = User(
            name="Priya Sharma",
            email="priya@example.com",
            password_hash="x",
            latitude=12.9781,
            longitude=77.6389,
        )
        product_a = Product(
            asin="B0SONY520",
            name="Sony WH-CH520 Wireless Headphones",
            price=Decimal("4990.00"),
            rating=4.5,
            review_count=120,
            image_url="https://img.example/sony.jpg",
            uploaded_image_path="/uploads/sony.jpg",
            estimated_reverse_logistics_cost=Decimal("200.00"),
        )
        product_b = Product(
            asin="B0LEVIS01",
            name="Levi's T-Shirt",
            price=Decimal("1299.00"),
            rating=4.2,
            review_count=80,
            image_url="https://img.example/levis.jpg",
            estimated_reverse_logistics_cost=Decimal("50.00"),
        )
        session.add_all([seller, product_a, product_b])
        await session.flush()

        purchased_a = datetime.now(timezone.utc) - timedelta(days=40)
        purchased_b = datetime.now(timezone.utc) - timedelta(days=20)
        order_a = OrderHistory(
            user_id=seller.id, product_id=product_a.id, purchased_at=purchased_a
        )
        order_b = OrderHistory(
            user_id=seller.id, product_id=product_b.id, purchased_at=purchased_b
        )
        session.add_all([order_a, order_b])
        await session.flush()

        # Older ACTIVE listing.
        older = ResaleListing(
            product_id=product_a.id,
            order_history_id=order_a.id,
            seller_id=seller.id,
            status=ResaleStatus.ACTIVE,
            condition_grade=ConditionGrade.GOOD,
            resale_price=Decimal("3000.00"),
            condition_image_url="https://img.example/cond-a.jpg",
            listed_at=datetime(2024, 1, 1, 9, 0, 0, tzinfo=timezone.utc),
        )
        # Newer ACTIVE listing (should sort first).
        newer = ResaleListing(
            product_id=product_b.id,
            order_history_id=order_b.id,
            seller_id=seller.id,
            status=ResaleStatus.ACTIVE,
            condition_grade=ConditionGrade.LIKE_NEW,
            resale_price=Decimal("900.00"),
            condition_image_url="https://img.example/cond-b.jpg",
            listed_at=datetime(2024, 2, 1, 9, 0, 0, tzinfo=timezone.utc),
        )
        # Non-active listing (SOLD) — must be excluded from the feed.
        sold = ResaleListing(
            product_id=product_a.id,
            order_history_id=order_a.id,
            seller_id=seller.id,
            status=ResaleStatus.SOLD,
            condition_grade=ConditionGrade.FAIR,
            resale_price=Decimal("2500.00"),
            condition_image_url="https://img.example/cond-sold.jpg",
            listed_at=datetime(2024, 3, 1, 9, 0, 0, tzinfo=timezone.utc),
        )
        session.add_all([older, newer, sold])
        await session.commit()
        return {
            "newer_id": newer.id,
            "older_id": older.id,
            "purchased_a": purchased_a,
            "purchased_b": purchased_b,
            "product_a_image": product_a.image_url,
        }


async def test_list_active_feed_returns_only_active_newest_first(
    sessionmaker_fixture,
) -> None:
    """Feed returns only ACTIVE listings, newest listed_at first, fully joined."""
    ids = await _seed_feed(sessionmaker_fixture)
    async with sessionmaker_fixture() as session:
        feed = await resale_service.list_active_feed(session)

    # Only the two ACTIVE listings, SOLD excluded (Req 12.1).
    assert [item.listing.id for item in feed] == [ids["newer_id"], ids["older_id"]]

    # Each carries the joined Product, both image URLs, and the purchase date.
    newer_item, older_item = feed
    assert newer_item.listing.product.image_url == "https://img.example/levis.jpg"
    assert newer_item.listing.condition_image_url == "https://img.example/cond-b.jpg"
    assert newer_item.original_purchased_at.replace(tzinfo=None) == ids[
        "purchased_b"
    ].replace(tzinfo=None)
    assert older_item.listing.product.image_url == ids["product_a_image"]
    assert older_item.listing.condition_image_url == "https://img.example/cond-a.jpg"
    assert older_item.original_purchased_at.replace(tzinfo=None) == ids[
        "purchased_a"
    ].replace(tzinfo=None)


async def test_list_active_feed_empty_returns_empty_list(sessionmaker_fixture) -> None:
    """No ACTIVE listings -> empty list, not an error (Req 12.2)."""
    async with sessionmaker_fixture() as session:
        feed = await resale_service.list_active_feed(session)
    assert feed == []


async def test_list_active_feed_store_failure_raises_store_unavailable(
    sessionmaker_fixture,
) -> None:
    """A store/query failure surfaces as StoreUnavailableError (Req 12.3)."""
    from sqlalchemy.exc import OperationalError

    async with sessionmaker_fixture() as session:
        async def _boom(*_args, **_kwargs):
            raise OperationalError("SELECT", {}, Exception("store down"))

        session.execute = _boom  # type: ignore[assignment]
        with pytest.raises(StoreUnavailableError):
            await resale_service.list_active_feed(session)


async def test_endpoint_feed_returns_active_items_newest_first(
    sessionmaker_fixture,
) -> None:
    """GET /api/resale/feed returns ACTIVE items, newest first, both images."""
    ids = await _seed_feed(sessionmaker_fixture)
    client = _build_client(sessionmaker_fixture)

    resp = client.get("/api/resale/feed")
    assert resp.status_code == 200
    body = resp.json()
    assert [item["id"] for item in body] == [ids["newer_id"], ids["older_id"]]

    first = body[0]
    assert first["status"] == "ACTIVE"
    assert first["condition_image_url"] == "https://img.example/cond-b.jpg"
    assert first["product"]["image_url"] == "https://img.example/levis.jpg"
    assert first["product"]["asin"] == "B0LEVIS01"
    assert "original_purchased_at" in first
    # The uploaded_image_path is surfaced when present on the product.
    assert body[1]["product"]["uploaded_image_path"] == "/uploads/sony.jpg"


async def test_endpoint_feed_empty_returns_empty_array(sessionmaker_fixture) -> None:
    """GET /api/resale/feed with no ACTIVE listings -> 200 [] (Req 12.2)."""
    client = _build_client(sessionmaker_fixture)
    resp = client.get("/api/resale/feed")
    assert resp.status_code == 200
    assert resp.json() == []
