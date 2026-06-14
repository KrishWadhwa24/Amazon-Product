"""Tests for return initiation and scanner-pool membership (task 8.1).

Covers the return service (``initiate_return``, ``scanner_pool_members``), the
signed-session helper, and the ``POST /api/returns/initiate`` endpoint wiring,
all against an in-memory async SQLite database so no PostgreSQL/Redis server is
required (Requirements 3.1, 3.2, 3.3, 3.7).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user_id
from app.core.errors import AuthError, NotEligibleError
from app.core.security import SESSION_COOKIE_NAME, read_session, sign_session
from app.db.base import Base
from app.db.session import get_session
from app.main import create_app
from app.models.enums import ReturnStatus
from app.models.order_history import OrderHistory
from app.models.product import Product
from app.models.return_order import ReturnOrder
from app.models.user import User
from app.services import returns as returns_service
from app.services.returns import RETURN_WINDOW_SECONDS


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
    """Seed two users, a product, and an order in seller's history.

    Returns a dict of useful ids: seller_id, other_user_id, product_id,
    order_history_id (belongs to seller).
    """
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
            purchased_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
        session.add(order)
        await session.commit()
        return {
            "seller_id": seller.id,
            "other_user_id": other.id,
            "product_id": product.id,
            "order_history_id": order.id,
            "asin": product.asin,
        }


# --------------------------------------------------------------------------- #
# Signed-session helper (security.py)
# --------------------------------------------------------------------------- #


def test_session_token_roundtrips_user_id() -> None:
    """A signed token resolves back to the same user id."""
    token = sign_session(42)
    assert read_session(token) == 42


def test_read_session_rejects_forged_token() -> None:
    """A tampered/garbage token resolves to None, not an exception."""
    assert read_session("not-a-valid-token") is None
    assert read_session("") is None


# --------------------------------------------------------------------------- #
# Return service — initiation (Requirements 3.1, 3.2, 3.7)
# --------------------------------------------------------------------------- #


async def test_initiate_return_creates_scanning_order_with_48h_window(
    sessionmaker_fixture,
) -> None:
    """A valid request creates SCANNING with an exact 172,800s window."""
    ids = await _seed(sessionmaker_fixture)
    fixed_now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    async with sessionmaker_fixture() as session:
        order = await returns_service.initiate_return(
            session,
            user_id=ids["seller_id"],
            order_history_id=ids["order_history_id"],
            now=fixed_now,
        )
        assert order.status == ReturnStatus.SCANNING
        assert order.seller_id == ids["seller_id"]
        assert order.asin == ids["asin"]
        # SQLite stores naive datetimes, so compare wall-clock and the exact
        # window length rather than tz identity (the service writes UTC-aware).
        assert order.initiated_at.replace(tzinfo=None) == fixed_now.replace(tzinfo=None)
        delta = order.expires_at - order.initiated_at
        assert delta.total_seconds() == RETURN_WINDOW_SECONDS == 172_800


async def test_initiate_return_without_session_raises_auth_error(
    sessionmaker_fixture,
) -> None:
    """No authenticated user -> AuthError and no ReturnOrder created (Req 3.7)."""
    ids = await _seed(sessionmaker_fixture)
    async with sessionmaker_fixture() as session:
        with pytest.raises(AuthError):
            await returns_service.initiate_return(
                session, user_id=None, order_history_id=ids["order_history_id"]
            )
        assert (await session.execute(_count_returns())).scalar_one() == 0


async def test_initiate_return_for_other_users_order_raises_not_eligible(
    sessionmaker_fixture,
) -> None:
    """Order not in requesting user's history -> NotEligibleError (Req 3.7)."""
    ids = await _seed(sessionmaker_fixture)
    async with sessionmaker_fixture() as session:
        with pytest.raises(NotEligibleError):
            await returns_service.initiate_return(
                session,
                user_id=ids["other_user_id"],
                order_history_id=ids["order_history_id"],
            )
        assert (await session.execute(_count_returns())).scalar_one() == 0


async def test_initiate_return_for_missing_order_raises_not_eligible(
    sessionmaker_fixture,
) -> None:
    """Unknown order_history_id -> NotEligibleError, no ReturnOrder."""
    ids = await _seed(sessionmaker_fixture)
    async with sessionmaker_fixture() as session:
        with pytest.raises(NotEligibleError):
            await returns_service.initiate_return(
                session, user_id=ids["seller_id"], order_history_id=999_999
            )


# --------------------------------------------------------------------------- #
# Scanner-pool membership (Requirement 3.3)
# --------------------------------------------------------------------------- #


async def test_scanner_pool_includes_only_scanning_nonexpired(
    sessionmaker_fixture,
) -> None:
    """Discoverable iff SCANNING and expires_at strictly later than now."""
    ids = await _seed(sessionmaker_fixture)
    now = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    async with sessionmaker_fixture() as session:
        # Discoverable: SCANNING, not yet expired.
        live = ReturnOrder(
            seller_id=ids["seller_id"],
            product_id=ids["product_id"],
            order_history_id=ids["order_history_id"],
            asin=ids["asin"],
            status=ReturnStatus.SCANNING,
            initiated_at=now - timedelta(hours=1),
            expires_at=now + timedelta(hours=47),
        )
        # Not discoverable: SCANNING but already expired.
        expired_window = ReturnOrder(
            seller_id=ids["seller_id"],
            product_id=ids["product_id"],
            order_history_id=ids["order_history_id"],
            asin=ids["asin"],
            status=ReturnStatus.SCANNING,
            initiated_at=now - timedelta(hours=49),
            expires_at=now - timedelta(hours=1),
        )
        # Not discoverable: non-SCANNING status.
        not_scanning = ReturnOrder(
            seller_id=ids["seller_id"],
            product_id=ids["product_id"],
            order_history_id=ids["order_history_id"],
            asin=ids["asin"],
            status=ReturnStatus.EXPIRED,
            initiated_at=now - timedelta(hours=1),
            expires_at=now + timedelta(hours=47),
        )
        session.add_all([live, expired_window, not_scanning])
        await session.commit()
        live_id = live.id

        members = await returns_service.scanner_pool_members(session, now=now)
        assert [m.id for m in members] == [live_id]


# --------------------------------------------------------------------------- #
# Endpoint wiring — POST /api/returns/initiate
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


async def test_endpoint_initiate_returns_201_with_valid_session(
    sessionmaker_fixture,
) -> None:
    """Authenticated owner gets 201 and a SCANNING return_order payload."""
    ids = await _seed(sessionmaker_fixture)
    client = _build_client(sessionmaker_fixture)
    client.cookies.set(SESSION_COOKIE_NAME, sign_session(ids["seller_id"]))

    resp = client.post(
        "/api/returns/initiate", json={"order_history_id": ids["order_history_id"]}
    )
    assert resp.status_code == 201
    body = resp.json()["return_order"]
    assert body["status"] == "SCANNING"
    assert body["seller_id"] == ids["seller_id"]
    assert body["asin"] == ids["asin"]


async def test_endpoint_initiate_rejects_anonymous_with_401(
    sessionmaker_fixture,
) -> None:
    """No session cookie -> 401 NO_SESSION envelope (Requirement 3.7)."""
    ids = await _seed(sessionmaker_fixture)
    client = _build_client(sessionmaker_fixture)

    resp = client.post(
        "/api/returns/initiate", json={"order_history_id": ids["order_history_id"]}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "NO_SESSION"


async def test_endpoint_initiate_rejects_non_owner_with_422(
    sessionmaker_fixture,
) -> None:
    """Order not in the user's history -> 422 RETURN_NOT_PERMITTED (Req 3.7)."""
    ids = await _seed(sessionmaker_fixture)
    client = _build_client(sessionmaker_fixture)
    client.cookies.set(SESSION_COOKIE_NAME, sign_session(ids["other_user_id"]))

    resp = client.post(
        "/api/returns/initiate", json={"order_history_id": ids["order_history_id"]}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "RETURN_NOT_PERMITTED"


# Helper select for counting ReturnOrders without importing select at top twice.
def _count_returns():
    from sqlalchemy import func, select

    return select(func.count()).select_from(ReturnOrder)
