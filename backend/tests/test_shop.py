"""Tests for the shop router — catalog reads + demand-signal endpoints (task 20.2).

Exercises ``app/api/shop.py`` against an in-memory async SQLite database with an
in-memory fake Redis gateway injected through the ``get_redis_gateway``
dependency override, so no PostgreSQL/Redis server is required (Requirements
4.1-4.7, 6.x, 1.8).

Headline scenario (Flow 18 / Requirement 1.8): Priya (seller) has a SCANNING
return for the Sony ASIN; Rahul (buyer ~5 km away) POSTs ``/api/cart`` for that
ASIN — a CartItem is created AND a PENDING MatchCandidate appears in the DB.
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

from app.api.shop import get_redis_gateway
from app.core.security import SESSION_COOKIE_NAME, sign_session
from app.db.base import Base
from app.db.session import get_session
from app.main import create_app
from app.models.cart_item import CartItem
from app.models.enums import MatchStatus, ReturnStatus
from app.models.match_candidate import MatchCandidate
from app.models.order_history import OrderHistory
from app.models.product import Product
from app.models.return_order import ReturnOrder
from app.models.user import User

# Seeded coordinates (Requirements 2.3/2.4); Priya↔Rahul is ~5 km.
PRIYA_LAT, PRIYA_LON = 12.9781, 77.6389  # seller
RAHUL_LAT, RAHUL_LON = 12.9352, 77.6271  # buyer ~5 km away


class FakeGateway:
    """Minimal in-memory stand-in for the Redis gateway used by record_signal."""

    def __init__(self) -> None:
        self.geo: dict[str, dict[str, tuple[float, float]]] = {}
        self.ts: dict[str, dict[str, int]] = {}

    async def geo_add(self, key: str, lon: float, lat: float, member: str) -> None:
        self.geo.setdefault(key, {})[member] = (lon, lat)

    async def hset_ts(self, key: str, member: str, epoch_ms: int) -> None:
        self.ts.setdefault(key, {})[member] = epoch_ms


@pytest.fixture(autouse=True)
def _naive_engine_clock(monkeypatch):
    """Patch the matching engine's clock to a naive UTC time.

    The endpoints call ``record_and_match`` without an explicit ``now``, which
    defaults to a tz-aware time. Under the SQLite test harness stored datetimes
    come back naive, so we patch the engine's ``_utcnow`` to a naive value to
    keep the in-Python window comparison naive-vs-naive. Production Postgres is
    tz-aware on both sides and needs no such patch.
    """
    import app.services.matching_engine as engine

    monkeypatch.setattr(engine, "_utcnow", datetime.utcnow)


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


async def _seed_catalog(factory) -> dict[str, object]:
    """Seed Priya (seller), Rahul (buyer), two products, and a SCANNING return.

    Uses naive UTC datetimes so the values round-trip through SQLite (which
    drops tzinfo) consistently with the patched naive engine clock; production
    Postgres is tz-aware on both sides.
    """
    now = datetime.utcnow()
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
        sony = Product(
            asin="B0SONY520",
            name="Sony WH-CH520 Wireless Headphones",
            price=Decimal("4990.00"),
            rating=4.5,
            review_count=120,
            image_url="https://img.example/sony.jpg",
            estimated_reverse_logistics_cost=Decimal("200.00"),
        )
        levis = Product(
            asin="B0LEVIS01",
            name="Levi's T-Shirt",
            price=Decimal("1299.00"),
            rating=4.2,
            review_count=80,
            image_url="https://img.example/levis.jpg",
            estimated_reverse_logistics_cost=Decimal("50.00"),
        )
        session.add_all([seller, buyer, sony, levis])
        await session.flush()
        order = OrderHistory(
            user_id=seller.id, product_id=sony.id, purchased_at=now - timedelta(days=3)
        )
        session.add(order)
        await session.flush()
        ret = ReturnOrder(
            seller_id=seller.id,
            product_id=sony.id,
            order_history_id=order.id,
            asin=sony.asin,
            status=ReturnStatus.SCANNING,
            initiated_at=now - timedelta(hours=1),
            expires_at=now + timedelta(hours=47),
        )
        session.add(ret)
        await session.commit()
        return {
            "seller_id": seller.id,
            "buyer_id": buyer.id,
            "sony_asin": sony.asin,
            "levis_asin": levis.asin,
            "return_id": ret.id,
        }


def _build_client(factory, gateway) -> TestClient:
    """Return a TestClient whose DB session + Redis gateway use test doubles."""
    app = create_app()

    async def _override_get_session():
        async with factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_redis_gateway] = lambda: gateway
    return TestClient(app)


# --------------------------------------------------------------------------- #
# Catalog reads (task 20.1)
# --------------------------------------------------------------------------- #


async def test_get_products_returns_catalog(sessionmaker_fixture) -> None:
    """GET /api/products returns the seeded catalog with the documented fields."""
    ids = await _seed_catalog(sessionmaker_fixture)
    client = _build_client(sessionmaker_fixture, FakeGateway())

    resp = client.get("/api/products")
    assert resp.status_code == 200
    body = resp.json()
    asins = {item["asin"] for item in body}
    assert {ids["sony_asin"], ids["levis_asin"]} <= asins
    sony = next(item for item in body if item["asin"] == ids["sony_asin"])
    for field in ("id", "asin", "name", "price", "rating", "review_count", "image_url"):
        assert field in sony
    assert sony["name"] == "Sony WH-CH520 Wireless Headphones"


async def test_get_product_by_asin_and_404(sessionmaker_fixture) -> None:
    """GET /api/products/{asin} returns the product, or 404 PRODUCT_NOT_FOUND."""
    ids = await _seed_catalog(sessionmaker_fixture)
    client = _build_client(sessionmaker_fixture, FakeGateway())

    ok = client.get(f"/api/products/{ids['sony_asin']}")
    assert ok.status_code == 200
    assert ok.json()["asin"] == ids["sony_asin"]

    missing = client.get("/api/products/B0DOESNOTEXIST")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "PRODUCT_NOT_FOUND"


# --------------------------------------------------------------------------- #
# Demand-signal endpoints (task 20.2)
# --------------------------------------------------------------------------- #


async def test_post_cart_creates_item_and_pending_match(sessionmaker_fixture) -> None:
    """POST /api/cart as Rahul creates a CartItem AND a PENDING MatchCandidate.

    This is the Flow 18 / Requirement 1.8 demo path: Priya's SCANNING Sony
    return + Rahul's nearby cart-add yields exactly one PENDING candidate.
    """
    ids = await _seed_catalog(sessionmaker_fixture)
    gateway = FakeGateway()
    client = _build_client(sessionmaker_fixture, gateway)
    client.cookies.set(SESSION_COOKIE_NAME, sign_session(ids["buyer_id"]))

    resp = client.post("/api/cart", json={"asin": ids["sony_asin"]})
    assert resp.status_code == 201
    body = resp.json()
    assert body["cart_item"]["product"]["asin"] == ids["sony_asin"]
    assert body["match_created"] is True

    # The cart signal was written to the (fake) geospatial index.
    assert f"demand:cart:{ids['sony_asin']}" in gateway.geo

    async with sessionmaker_fixture() as session:
        cart_count = (
            await session.execute(
                select(func.count())
                .select_from(CartItem)
                .where(CartItem.user_id == ids["buyer_id"])
            )
        ).scalar_one()
        assert cart_count == 1

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
        assert pending == 1


async def test_get_cart_returns_items_with_product(sessionmaker_fixture) -> None:
    """GET /api/cart returns the buyer's items joined with product info."""
    ids = await _seed_catalog(sessionmaker_fixture)
    gateway = FakeGateway()
    client = _build_client(sessionmaker_fixture, gateway)
    client.cookies.set(SESSION_COOKIE_NAME, sign_session(ids["buyer_id"]))

    client.post("/api/cart", json={"asin": ids["sony_asin"]})

    resp = client.get("/api/cart")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["product"]["asin"] == ids["sony_asin"]
    assert items[0]["product"]["name"] == "Sony WH-CH520 Wireless Headphones"


async def test_demand_endpoints_status_codes(sessionmaker_fixture) -> None:
    """buynow/wishlist -> 201, view -> 202; each acknowledges the recording."""
    ids = await _seed_catalog(sessionmaker_fixture)
    gateway = FakeGateway()
    client = _build_client(sessionmaker_fixture, gateway)
    client.cookies.set(SESSION_COOKIE_NAME, sign_session(ids["buyer_id"]))

    assert client.post("/api/buynow", json={"asin": ids["levis_asin"]}).status_code == 201
    assert client.post("/api/wishlist", json={"asin": ids["levis_asin"]}).status_code == 201
    assert client.post("/api/view", json={"asin": ids["levis_asin"]}).status_code == 202

    # Each intent wrote its own demand key for the Levi's ASIN.
    for intent in ("buynow", "wishlist", "viewed"):
        assert f"demand:{intent}:{ids['levis_asin']}" in gateway.geo


async def test_cart_requires_authentication(sessionmaker_fixture) -> None:
    """An anonymous POST /api/cart is rejected with 401 NO_SESSION."""
    ids = await _seed_catalog(sessionmaker_fixture)
    client = _build_client(sessionmaker_fixture, FakeGateway())

    resp = client.post("/api/cart", json={"asin": ids["sony_asin"]})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "NO_SESSION"


async def test_signal_storage_failure_maps_to_502(sessionmaker_fixture) -> None:
    """A Redis write failure surfaces as 502 SIGNAL_NOT_RECORDED (Req 4.7)."""
    from app.db.redis_gateway import SignalStorageError

    ids = await _seed_catalog(sessionmaker_fixture)

    class BoomGateway(FakeGateway):
        async def geo_add(self, key, lon, lat, member):  # type: ignore[override]
            raise SignalStorageError("redis down")

    client = _build_client(sessionmaker_fixture, BoomGateway())
    client.cookies.set(SESSION_COOKIE_NAME, sign_session(ids["buyer_id"]))

    resp = client.post("/api/buynow", json={"asin": ids["sony_asin"]})
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "SIGNAL_NOT_RECORDED"
