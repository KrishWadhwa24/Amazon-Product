"""Tests for auth endpoints and the auth service (task 14.1).

Covers ``app.services.auth`` (``verify_credentials``, ``can_sell``) and the
``/api/auth/*`` endpoint wiring (login/logout/session), all against an
in-memory async SQLite database with a FastAPI TestClient so no PostgreSQL /
Redis server is required (Requirements 1.2, 1.3, 1.4, 1.5, 1.6).

Passwords are bcrypt-hashed in the seed exactly as ``seed.py`` does, so the
verification path exercises real hashing rather than a stub.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.errors import LoginFailedError
from app.core.security import SESSION_COOKIE_NAME, sign_session
from app.db.base import Base
from app.db.session import get_session
from app.main import create_app
from app.models.enums import UserRole
from app.models.order_history import OrderHistory
from app.models.product import Product
from app.models.user import User
from app.services import auth as auth_service

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Demo credentials mirroring seed.py.
SELLER_EMAIL = "priya.sharma@example.com"
SELLER_PASSWORD = "priya"
BUYER_EMAIL = "rahul.verma@example.com"
BUYER_PASSWORD = "rahul"


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
    """Seed a Seller (with order history) and a Buyer (no order history).

    Returns useful ids: seller_id, buyer_id, product_id.
    """
    async with factory() as session:
        seller = User(
            name="Priya Sharma",
            email=SELLER_EMAIL,
            password_hash=_pwd_context.hash(SELLER_PASSWORD),
            role=UserRole.SELLER,
            latitude=12.9781,
            longitude=77.6389,
        )
        buyer = User(
            name="Rahul Verma",
            email=BUYER_EMAIL,
            password_hash=_pwd_context.hash(BUYER_PASSWORD),
            role=UserRole.BUYER,
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
        # Seller has order history (can_sell == True); buyer has none.
        order = OrderHistory(
            user_id=seller.id,
            product_id=product.id,
            purchased_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
        session.add(order)
        await session.commit()
        return {
            "seller_id": seller.id,
            "buyer_id": buyer.id,
            "product_id": product.id,
        }


# --------------------------------------------------------------------------- #
# Service layer — verify_credentials / can_sell (Requirements 1.2, 1.3, 1.5)
# --------------------------------------------------------------------------- #


async def test_verify_credentials_returns_user_on_match(sessionmaker_fixture) -> None:
    """Correct email + password resolves to the seeded user (Req 1.2)."""
    ids = await _seed(sessionmaker_fixture)
    async with sessionmaker_fixture() as session:
        user = await auth_service.verify_credentials(
            session, SELLER_EMAIL, SELLER_PASSWORD
        )
        assert user.id == ids["seller_id"]


async def test_verify_credentials_is_case_insensitive_on_email(
    sessionmaker_fixture,
) -> None:
    """Email lookup ignores case (Req 1.2)."""
    ids = await _seed(sessionmaker_fixture)
    async with sessionmaker_fixture() as session:
        user = await auth_service.verify_credentials(
            session, SELLER_EMAIL.upper(), SELLER_PASSWORD
        )
        assert user.id == ids["seller_id"]


async def test_verify_credentials_wrong_password_raises(sessionmaker_fixture) -> None:
    """A bad password raises LoginFailedError (Req 1.3)."""
    await _seed(sessionmaker_fixture)
    async with sessionmaker_fixture() as session:
        with pytest.raises(LoginFailedError):
            await auth_service.verify_credentials(session, SELLER_EMAIL, "wrong")


async def test_verify_credentials_unknown_email_raises(sessionmaker_fixture) -> None:
    """An unknown email raises LoginFailedError (Req 1.3)."""
    await _seed(sessionmaker_fixture)
    async with sessionmaker_fixture() as session:
        with pytest.raises(LoginFailedError):
            await auth_service.verify_credentials(
                session, "nobody@example.com", "whatever"
            )


async def test_can_sell_true_with_order_history(sessionmaker_fixture) -> None:
    """A user with OrderHistory may act as a Seller (Req 1.5)."""
    ids = await _seed(sessionmaker_fixture)
    async with sessionmaker_fixture() as session:
        assert await auth_service.can_sell(session, ids["seller_id"]) is True


async def test_can_sell_false_without_order_history(sessionmaker_fixture) -> None:
    """A user without OrderHistory cannot act as a Seller (Req 1.5)."""
    ids = await _seed(sessionmaker_fixture)
    async with sessionmaker_fixture() as session:
        assert await auth_service.can_sell(session, ids["buyer_id"]) is False


# --------------------------------------------------------------------------- #
# Endpoint wiring — /api/auth/* (Requirements 1.2–1.6)
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


async def test_login_sets_cookie_and_returns_can_sell_true(sessionmaker_fixture) -> None:
    """Successful login sets the session cookie and reports can_sell (Req 1.2, 1.5)."""
    ids = await _seed(sessionmaker_fixture)
    client = _build_client(sessionmaker_fixture)

    resp = client.post(
        "/api/auth/login",
        json={"email": SELLER_EMAIL, "password": SELLER_PASSWORD},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == ids["seller_id"]
    assert body["name"] == "Priya Sharma"
    assert body["role"] == "Seller"
    assert body["can_sell"] is True
    # The signed session cookie is set on the response.
    assert SESSION_COOKIE_NAME in resp.cookies


async def test_login_buyer_reports_can_sell_false(sessionmaker_fixture) -> None:
    """A buyer with no order history logs in with can_sell false (Req 1.5)."""
    await _seed(sessionmaker_fixture)
    client = _build_client(sessionmaker_fixture)

    resp = client.post(
        "/api/auth/login",
        json={"email": BUYER_EMAIL, "password": BUYER_PASSWORD},
    )
    assert resp.status_code == 200
    assert resp.json()["can_sell"] is False


async def test_login_wrong_password_returns_401_auth_failed(
    sessionmaker_fixture,
) -> None:
    """A credential mismatch returns 401 AUTH_FAILED and sets no cookie (Req 1.3)."""
    await _seed(sessionmaker_fixture)
    client = _build_client(sessionmaker_fixture)

    resp = client.post(
        "/api/auth/login",
        json={"email": SELLER_EMAIL, "password": "wrong"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTH_FAILED"
    assert SESSION_COOKIE_NAME not in resp.cookies


async def test_session_without_cookie_returns_401_no_session(
    sessionmaker_fixture,
) -> None:
    """GET /session without a cookie returns 401 NO_SESSION (Req 1.4)."""
    await _seed(sessionmaker_fixture)
    client = _build_client(sessionmaker_fixture)

    resp = client.get("/api/auth/session")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "NO_SESSION"


async def test_session_with_cookie_returns_user(sessionmaker_fixture) -> None:
    """GET /session with a valid cookie returns the active user (Req 1.4)."""
    ids = await _seed(sessionmaker_fixture)
    client = _build_client(sessionmaker_fixture)
    client.cookies.set(SESSION_COOKIE_NAME, sign_session(ids["seller_id"]))

    resp = client.get("/api/auth/session")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == ids["seller_id"]
    assert body["name"] == "Priya Sharma"
    assert body["can_sell"] is True


async def test_login_then_session_roundtrip(sessionmaker_fixture) -> None:
    """The cookie set by login resolves the same user on /session (Req 1.2, 1.4)."""
    ids = await _seed(sessionmaker_fixture)
    client = _build_client(sessionmaker_fixture)

    login_resp = client.post(
        "/api/auth/login",
        json={"email": SELLER_EMAIL, "password": SELLER_PASSWORD},
    )
    assert login_resp.status_code == 200

    # TestClient persists cookies, so the next call carries the session.
    session_resp = client.get("/api/auth/session")
    assert session_resp.status_code == 200
    assert session_resp.json()["user_id"] == ids["seller_id"]


async def test_logout_clears_cookie_and_ends_session(sessionmaker_fixture) -> None:
    """Logout clears the cookie so a later /session is unauthenticated (Req 1.6)."""
    ids = await _seed(sessionmaker_fixture)
    client = _build_client(sessionmaker_fixture)
    client.cookies.set(SESSION_COOKIE_NAME, sign_session(ids["seller_id"]))

    logout_resp = client.post("/api/auth/logout")
    assert logout_resp.status_code == 204

    # The server instructed the client to delete the cookie; clear and confirm
    # that a subsequent request resolves to no session.
    client.cookies.clear()
    session_resp = client.get("/api/auth/session")
    assert session_resp.status_code == 401
    assert session_resp.json()["error"]["code"] == "NO_SESSION"
