"""Tests for the matching engine I/O shell and demand→match orchestration
(task 10.1).

Covers :func:`app.services.matching_engine.run_matching_for_signal` and the
:func:`app.services.matching_engine.record_and_match` orchestrator against an
in-memory async SQLite database (the pattern from ``tests/test_expiry_sweep.py``)
so no PostgreSQL/Redis server is required (Requirements 6.1, 6.5, 6.6, 6.7, 6.9,
6.10, 9.1).

A tiny in-memory :class:`FakeGateway` stands in for Redis so ``record_signal``'s
write succeeds without a live server; the match creation it triggers is what we
assert on.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.enums import MatchStatus, NotificationStatus, ReturnStatus
from app.models.match_candidate import MatchCandidate
from app.models.notification import Notification
from app.models.order_history import OrderHistory
from app.models.product import Product
from app.models.return_order import ReturnOrder
from app.models.user import User
from app.services.analytics import get_active_match_count
from app.services.matching_engine import record_and_match, run_matching_for_signal

# Seeded coordinates from Requirement 2.3/2.4.
PRIYA_LAT, PRIYA_LON = 12.9781, 77.6389  # seller
RAHUL_LAT, RAHUL_LON = 12.9352, 77.6271  # buyer ~5 km away

# SQLite returns naive datetimes, so we keep the reference clock naive to match
# what the stored ReturnOrder.expires_at deserializes to (the production
# Postgres path is tz-aware on both sides). Mirrors tests/test_returns.py.
NOW = datetime(2024, 6, 1, 0, 0, 0)


class FakeGateway:
    """Minimal in-memory stand-in for the Redis gateway used by record_signal."""

    def __init__(self) -> None:
        self.geo: dict[str, dict[str, tuple[float, float]]] = {}
        self.ts: dict[str, dict[str, int]] = {}

    async def geo_add(self, key: str, lon: float, lat: float, member: str) -> None:
        self.geo.setdefault(key, {})[member] = (lon, lat)

    async def hset_ts(self, key: str, member: str, epoch_ms: int) -> None:
        self.ts.setdefault(key, {})[member] = epoch_ms


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


async def _seed_with_scanning_return(factory) -> dict[str, int | str]:
    """Seed Priya (seller), Rahul (buyer), a product, and a SCANNING return."""
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
        await session.commit()
        return {
            "seller_id": seller.id,
            "buyer_id": buyer.id,
            "asin": product.asin,
            "return_id": ret.id,
        }


def _count_pending(return_id: int, buyer_id: int):
    return (
        select(func.count())
        .select_from(MatchCandidate)
        .where(
            MatchCandidate.return_order_id == return_id,
            MatchCandidate.buyer_id == buyer_id,
            MatchCandidate.status == MatchStatus.PENDING,
        )
    )


# --------------------------------------------------------------------------- #
# record_and_match creates exactly one PENDING candidate (Req 6.1, 6.5, 6.7, 9.1)
# --------------------------------------------------------------------------- #


async def test_record_and_match_creates_single_pending_candidate(
    sessionmaker_fixture,
) -> None:
    """A nearby cart signal creates one PENDING candidate ~5 km away, source cart."""
    ids = await _seed_with_scanning_return(sessionmaker_fixture)
    gateway = FakeGateway()

    async with sessionmaker_fixture() as session:
        result, match = await record_and_match(
            session,
            "cart",
            str(ids["asin"]),
            ids["buyer_id"],
            RAHUL_LON,
            RAHUL_LAT,
            gateway=gateway,
            recorded_at_ms=1_717_200_000_000,
            now=NOW,
        )

    assert result.intent == "cart"
    assert match is not None
    assert match.status == MatchStatus.PENDING
    assert match.signal_source == "cart"
    # Priya↔Rahul is ~5 km; well inside the 20 km Match_Radius.
    assert 4.0 <= match.distance_km <= 6.0
    # Cached deal impact present (Requirement 7): 12% of 4990 = 598.80.
    assert match.local_discount == Decimal("598.80")

    async with sessionmaker_fixture() as session:
        pending = (
            await session.execute(_count_pending(ids["return_id"], ids["buyer_id"]))
        ).scalar_one()
        assert pending == 1
        # Active-match counter bumped once (Requirement 6.7).
        assert await get_active_match_count(session) == 1
        # A PENDING notification was enqueued (Requirement 6.6).
        notif_count = (
            await session.execute(
                select(func.count())
                .select_from(Notification)
                .where(Notification.status == NotificationStatus.PENDING)
            )
        ).scalar_one()
        assert notif_count == 1


# --------------------------------------------------------------------------- #
# Duplicate guard — a second identical signal creates no duplicate (Req 6.9)
# --------------------------------------------------------------------------- #


async def test_second_identical_signal_creates_no_duplicate(
    sessionmaker_fixture,
) -> None:
    """Re-processing the same (buyer, return) pair adds no second PENDING row."""
    ids = await _seed_with_scanning_return(sessionmaker_fixture)
    gateway = FakeGateway()

    async with sessionmaker_fixture() as session:
        _, first = await record_and_match(
            session, "cart", str(ids["asin"]), ids["buyer_id"],
            RAHUL_LON, RAHUL_LAT, gateway=gateway,
            recorded_at_ms=1_717_200_000_000, now=NOW,
        )
        assert first is not None

    async with sessionmaker_fixture() as session:
        _, second = await record_and_match(
            session, "cart", str(ids["asin"]), ids["buyer_id"],
            RAHUL_LON, RAHUL_LAT, gateway=gateway,
            recorded_at_ms=1_717_200_001_000, now=NOW,
        )
        # Duplicate guarded -> no new candidate returned (Requirement 6.9).
        assert second is None

    async with sessionmaker_fixture() as session:
        pending = (
            await session.execute(_count_pending(ids["return_id"], ids["buyer_id"]))
        ).scalar_one()
        assert pending == 1
        # Counter not bumped a second time.
        assert await get_active_match_count(session) == 1


# --------------------------------------------------------------------------- #
# Far buyer (>20 km) qualifies for nothing (Req 6.8, 6.10)
# --------------------------------------------------------------------------- #


async def test_far_buyer_creates_no_candidate(sessionmaker_fixture) -> None:
    """A buyer well beyond the 20 km radius produces no MatchCandidate."""
    ids = await _seed_with_scanning_return(sessionmaker_fixture)
    gateway = FakeGateway()

    # ~0.3 degrees of latitude south of Priya is ~33 km away (> 20 km radius).
    far_lat, far_lon = 12.6781, 77.6389

    async with sessionmaker_fixture() as session:
        _, match = await record_and_match(
            session, "cart", str(ids["asin"]), ids["buyer_id"],
            far_lon, far_lat, gateway=gateway,
            recorded_at_ms=1_717_200_000_000, now=NOW,
        )
        assert match is None

    async with sessionmaker_fixture() as session:
        total = (
            await session.execute(select(func.count()).select_from(MatchCandidate))
        ).scalar_one()
        assert total == 0
        assert await get_active_match_count(session) == 0


# --------------------------------------------------------------------------- #
# Direct shell entry point: no scanning return -> None (Req 6.10)
# --------------------------------------------------------------------------- #


async def test_run_matching_no_candidates_returns_none(sessionmaker_fixture) -> None:
    """run_matching_for_signal with no SCANNING return for the ASIN creates nothing."""
    ids = await _seed_with_scanning_return(sessionmaker_fixture)

    async with sessionmaker_fixture() as session:
        match = await run_matching_for_signal(
            session,
            asin="B0NONEXIST",  # no return for this ASIN
            buyer_id=int(ids["buyer_id"]),
            signal_source="cart",
            buyer_lat=RAHUL_LAT,
            buyer_lon=RAHUL_LON,
            now=NOW,
        )
        assert match is None
        total = (
            await session.execute(select(func.count()).select_from(MatchCandidate))
        ).scalar_one()
        assert total == 0
