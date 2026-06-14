"""Tests for the match candidate lifecycle service (task 11.1).

Covers :func:`app.services.matches.accept_match` and
:func:`app.services.matches.reject_match` against an in-memory async SQLite
database (the pattern from ``tests/test_matching_engine.py``) so no
PostgreSQL/Redis server is required.

Scenarios (Requirements 9.2–9.8):

* accepting a PENDING candidate as its buyer sets it ACCEPTED, advances the
  ReturnOrder all the way to LOCAL_DELIVERY, and EXPIRES the sibling PENDING
  candidate for the other buyer (Requirements 9.2, 9.5, 9.8);
* accepting a non-PENDING candidate raises OfferUnavailableError / 409
  (Requirement 9.6);
* acting as a non-owner raises ForbiddenError / 403 (Requirement 9.7);
* rejecting a PENDING candidate as its buyer sets it REJECTED (Requirement 9.3).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import StaticPool
from sqlalchemy import select

from app.core.errors import ForbiddenError, OfferUnavailableError
from app.db.base import Base
from app.models.enums import MatchStatus, ReturnStatus
from app.models.match_candidate import MatchCandidate
from app.models.order_history import OrderHistory
from app.models.product import Product
from app.models.return_order import ReturnOrder
from app.models.user import User
from app.services import matches as matches_service

PRIYA_LAT, PRIYA_LON = 12.9781, 77.6389  # seller
RAHUL_LAT, RAHUL_LON = 12.9352, 77.6271  # buyer A
ANITA_LAT, ANITA_LON = 12.9400, 77.6300  # buyer B

# SQLite stores naive datetimes; keep the reference clock naive to match.
NOW = datetime(2024, 6, 1, 0, 0, 0)


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


async def _seed_return_with_two_pending(factory) -> dict[str, int]:
    """Seed a SCANNING return with two PENDING candidates for two buyers."""
    async with factory() as session:
        seller = User(
            name="Priya Sharma",
            email="priya@example.com",
            password_hash="x",
            latitude=PRIYA_LAT,
            longitude=PRIYA_LON,
        )
        buyer_a = User(
            name="Rahul Verma",
            email="rahul@example.com",
            password_hash="x",
            latitude=RAHUL_LAT,
            longitude=RAHUL_LON,
        )
        buyer_b = User(
            name="Anita Rao",
            email="anita@example.com",
            password_hash="x",
            latitude=ANITA_LAT,
            longitude=ANITA_LON,
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
        session.add_all([seller, buyer_a, buyer_b, product])
        await session.flush()
        order = OrderHistory(
            user_id=seller.id,
            product_id=product.id,
            purchased_at=NOW - timedelta(days=3),
        )
        session.add(order)
        await session.flush()
        ret = ReturnOrder(
            seller_id=seller.id,
            product_id=product.id,
            order_history_id=order.id,
            asin=product.asin,
            status=ReturnStatus.SCANNING,
            initiated_at=NOW - timedelta(hours=1),
            expires_at=NOW + timedelta(hours=47),
        )
        session.add(ret)
        await session.flush()
        cand_a = MatchCandidate(
            return_order_id=ret.id,
            buyer_id=buyer_a.id,
            status=MatchStatus.PENDING,
            distance_km=5.0,
            signal_source="cart",
            local_discount=Decimal("598.80"),
            delivery_time_saved_hours=24,
            carbon_avoided_kg=1.2,
            created_at=NOW,
        )
        cand_b = MatchCandidate(
            return_order_id=ret.id,
            buyer_id=buyer_b.id,
            status=MatchStatus.PENDING,
            distance_km=4.0,
            signal_source="buynow",
            local_discount=Decimal("598.80"),
            delivery_time_saved_hours=24,
            carbon_avoided_kg=1.2,
            created_at=NOW,
        )
        session.add_all([cand_a, cand_b])
        await session.commit()
        return {
            "seller_id": seller.id,
            "buyer_a_id": buyer_a.id,
            "buyer_b_id": buyer_b.id,
            "return_id": ret.id,
            "cand_a_id": cand_a.id,
            "cand_b_id": cand_b.id,
        }


async def _load(session: AsyncSession, match_id: int) -> MatchCandidate:
    stmt = (
        select(MatchCandidate)
        .where(MatchCandidate.id == match_id)
        .options(selectinload(MatchCandidate.return_order))
    )
    return (await session.execute(stmt)).scalar_one()


# --------------------------------------------------------------------------- #
# Accept: candidate ACCEPTED, return -> LOCAL_DELIVERY, sibling EXPIRED
# (Requirements 9.2, 9.5, 9.8)
# --------------------------------------------------------------------------- #


async def test_accept_sets_accepted_advances_return_and_expires_sibling(
    sessionmaker_fixture,
) -> None:
    ids = await _seed_return_with_two_pending(sessionmaker_fixture)

    async with sessionmaker_fixture() as session:
        candidate = await _load(session, ids["cand_a_id"])
        accepted = await matches_service.accept_match(
            session, candidate, user_id=ids["buyer_a_id"]
        )
        assert accepted.status == MatchStatus.ACCEPTED

    async with sessionmaker_fixture() as session:
        cand_a = await _load(session, ids["cand_a_id"])
        cand_b = await _load(session, ids["cand_b_id"])
        ret = await session.get(ReturnOrder, ids["return_id"])
        # Accepted candidate ACCEPTED (Req 9.2).
        assert cand_a.status == MatchStatus.ACCEPTED
        # Return advanced all the way to LOCAL_DELIVERY (Req 9.5).
        assert ret.status == ReturnStatus.LOCAL_DELIVERY
        # The other PENDING sibling is EXPIRED (Req 9.8).
        assert cand_b.status == MatchStatus.EXPIRED


# --------------------------------------------------------------------------- #
# Accept a non-PENDING candidate -> 409 OFFER_UNAVAILABLE (Requirement 9.6)
# --------------------------------------------------------------------------- #


async def test_accept_non_pending_raises_offer_unavailable(
    sessionmaker_fixture,
) -> None:
    ids = await _seed_return_with_two_pending(sessionmaker_fixture)

    # First accept makes cand_a ACCEPTED (and cand_b EXPIRED).
    async with sessionmaker_fixture() as session:
        candidate = await _load(session, ids["cand_a_id"])
        await matches_service.accept_match(
            session, candidate, user_id=ids["buyer_a_id"]
        )

    # Re-accepting the now-EXPIRED sibling is rejected with OFFER_UNAVAILABLE.
    async with sessionmaker_fixture() as session:
        cand_b = await _load(session, ids["cand_b_id"])
        with pytest.raises(OfferUnavailableError) as exc:
            await matches_service.accept_match(
                session, cand_b, user_id=ids["buyer_b_id"]
            )
        assert exc.value.http_status == 409
        assert exc.value.code == "OFFER_UNAVAILABLE"

    async with sessionmaker_fixture() as session:
        cand_b = await _load(session, ids["cand_b_id"])
        assert cand_b.status == MatchStatus.EXPIRED  # unchanged


# --------------------------------------------------------------------------- #
# Acting as a non-owner -> 403 NOT_AUTHORIZED (Requirement 9.7)
# --------------------------------------------------------------------------- #


async def test_accept_as_non_owner_raises_forbidden(sessionmaker_fixture) -> None:
    ids = await _seed_return_with_two_pending(sessionmaker_fixture)

    async with sessionmaker_fixture() as session:
        candidate = await _load(session, ids["cand_a_id"])
        # buyer_b is not the owner of cand_a.
        with pytest.raises(ForbiddenError) as exc:
            await matches_service.accept_match(
                session, candidate, user_id=ids["buyer_b_id"]
            )
        assert exc.value.http_status == 403
        assert exc.value.code == "NOT_AUTHORIZED"

    async with sessionmaker_fixture() as session:
        cand_a = await _load(session, ids["cand_a_id"])
        ret = await session.get(ReturnOrder, ids["return_id"])
        # Nothing changed (Req 9.7).
        assert cand_a.status == MatchStatus.PENDING
        assert ret.status == ReturnStatus.SCANNING


async def test_reject_as_non_owner_raises_forbidden(sessionmaker_fixture) -> None:
    ids = await _seed_return_with_two_pending(sessionmaker_fixture)

    async with sessionmaker_fixture() as session:
        candidate = await _load(session, ids["cand_a_id"])
        with pytest.raises(ForbiddenError):
            await matches_service.reject_match(
                session, candidate, user_id=ids["buyer_b_id"]
            )


# --------------------------------------------------------------------------- #
# Reject sets REJECTED (Requirement 9.3)
# --------------------------------------------------------------------------- #


async def test_reject_sets_rejected(sessionmaker_fixture) -> None:
    ids = await _seed_return_with_two_pending(sessionmaker_fixture)

    async with sessionmaker_fixture() as session:
        candidate = await _load(session, ids["cand_a_id"])
        rejected = await matches_service.reject_match(
            session, candidate, user_id=ids["buyer_a_id"]
        )
        assert rejected.status == MatchStatus.REJECTED

    async with sessionmaker_fixture() as session:
        cand_a = await _load(session, ids["cand_a_id"])
        cand_b = await _load(session, ids["cand_b_id"])
        ret = await session.get(ReturnOrder, ids["return_id"])
        assert cand_a.status == MatchStatus.REJECTED
        # Rejecting one buyer does not retire the return or the sibling.
        assert cand_b.status == MatchStatus.PENDING
        assert ret.status == ReturnStatus.SCANNING
