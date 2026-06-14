"""Integration smoke tests for the seed script (task 3.2).

These exercise ``seed.run_seed`` end-to-end against a real (file-backed) async
SQLite database so no PostgreSQL or Redis server is required. They verify:

* a seed against an empty DB succeeds and produces the expected rows
  (Requirements 2.1, 2.3-2.6);
* a second seed against the now-populated DB still succeeds and does not
  duplicate rows — proving the drop phase is idempotent (Requirement 2.1);
* a per-phase failure aborts with a ``SeedPhaseError`` naming the failed phase
  and leaves no partially-populated data committed (Requirement 2.2);
* the Redis demand-key flush is invoked on the non-skip path and untouched on
  the ``skip_redis`` path (Requirement 2.7).

The database URL is passed explicitly to ``run_seed(database_url=..., skip_redis=
True)`` so the tests never read environment configuration or open a real engine
against PostgreSQL.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import seed
from app.models import OrderHistory, Product, User
from seed import (
    ASIN_LEVIS,
    ASIN_SONY,
    PHASE_POPULATE,
    PRIYA_EMAIL,
    RAHUL_EMAIL,
    SeedPhaseError,
    run_seed,
    run_smoke,
)


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture
def sqlite_url(tmp_path) -> str:
    """A temp-file SQLite URL that survives across independent engines.

    A file-backed DB (rather than ``:memory:``) is required because each
    ``run_seed`` call builds and disposes its own engine; verification then
    reconnects with a separate engine and must observe the committed rows.
    ``as_posix()`` yields forward slashes so the URL is valid on Windows.
    """
    db_path = (tmp_path / "seed_it.db").as_posix()
    return f"sqlite+aiosqlite:///{db_path}"


async def _table_counts(url: str) -> dict[str, int]:
    """Reconnect with a fresh engine and return row counts for key tables."""
    engine = create_async_engine(url, future=True)
    try:
        async with AsyncSession(bind=engine) as session:
            users = (await session.execute(select(func.count()).select_from(User))).scalar_one()
            products = (
                await session.execute(select(func.count()).select_from(Product))
            ).scalar_one()
            orders = (
                await session.execute(select(func.count()).select_from(OrderHistory))
            ).scalar_one()
            return {"users": users, "products": products, "order_history": orders}
    finally:
        await engine.dispose()


# --------------------------------------------------------------------------- #
# Empty-DB seed: success + expected rows (Requirements 2.1, 2.3-2.6)
# --------------------------------------------------------------------------- #
async def test_seed_empty_db_succeeds_and_populates_expected_rows(sqlite_url) -> None:
    """Seeding an empty DB succeeds and creates the required seed data."""
    summary = await run_seed(database_url=sqlite_url, skip_redis=True)

    # Summary reflects 2 users and a 5-50 product catalog (Requirements 2.3-2.5).
    assert summary["users"] == 2
    assert 5 <= summary["products"] <= 50
    assert summary["order_history"] >= 2

    engine = create_async_engine(sqlite_url, future=True)
    try:
        async with AsyncSession(bind=engine) as session:
            # Both required users exist (Requirements 2.3, 2.4).
            priya = (
                await session.execute(select(User).where(User.email == PRIYA_EMAIL))
            ).scalar_one()
            rahul = (
                await session.execute(select(User).where(User.email == RAHUL_EMAIL))
            ).scalar_one()
            assert priya.name == "Priya Sharma"
            assert (priya.latitude, priya.longitude) == (12.9781, 77.6389)
            assert rahul.name == "Rahul Verma"
            assert (rahul.latitude, rahul.longitude) == (12.9352, 77.6271)

            # Catalog size in range and contains the two required products
            # (Requirements 2.5, 2.6).
            product_names = set(
                (await session.execute(select(Product.name))).scalars().all()
            )
            assert 5 <= len(product_names) <= 50
            assert "Sony WH-CH520 Wireless Headphones" in product_names
            assert "Levi's T-Shirt" in product_names

            # Every product has a unique non-empty ASIN (Requirement 2.5).
            asins = (await session.execute(select(Product.asin))).scalars().all()
            assert all(a for a in asins)
            assert len(asins) == len(set(asins))

            # >= 2 past-dated OrderHistory rows for Priya referencing the two
            # required products (Requirement 2.6).
            priya_orders = (
                await session.execute(
                    select(OrderHistory).where(OrderHistory.user_id == priya.id)
                )
            ).scalars().all()
            assert len(priya_orders) >= 2
            ordered_product_ids = {o.product_id for o in priya_orders}
            sony = (
                await session.execute(select(Product).where(Product.asin == ASIN_SONY))
            ).scalar_one()
            levis = (
                await session.execute(select(Product).where(Product.asin == ASIN_LEVIS))
            ).scalar_one()
            assert sony.id in ordered_product_ids
            assert levis.id in ordered_product_ids
    finally:
        await engine.dispose()


# --------------------------------------------------------------------------- #
# Idempotent re-seed: success + no duplication (Requirement 2.1)
# --------------------------------------------------------------------------- #
async def test_seed_is_idempotent_against_populated_db(sqlite_url) -> None:
    """Re-seeding a populated DB still succeeds and produces identical counts."""
    first = await run_seed(database_url=sqlite_url, skip_redis=True)
    counts_after_first = await _table_counts(sqlite_url)

    # Second run against the now-populated DB: drop is idempotent (Req 2.1).
    second = await run_seed(database_url=sqlite_url, skip_redis=True)
    counts_after_second = await _table_counts(sqlite_url)

    assert first == second
    # No duplication: the drop -> recreate -> populate cycle yields the same
    # row counts, not double (Requirement 2.1).
    assert counts_after_first == counts_after_second
    assert counts_after_second["users"] == 2


# --------------------------------------------------------------------------- #
# Per-phase failure: abort + no partial commit (Requirement 2.2)
# --------------------------------------------------------------------------- #
async def test_populate_failure_raises_phase_error_and_commits_nothing(
    sqlite_url, monkeypatch
) -> None:
    """A failure during populate rolls back with no partial data (Req 2.2)."""

    async def _failing_populate(session: AsyncSession) -> dict[str, int]:
        # Add a row, then fail before the caller commits: the caller's rollback
        # must prevent this partial row from being committed (Requirement 2.2).
        session.add(
            User(
                name="Partial User",
                email="partial@example.com",
                password_hash="x",
                latitude=0.0,
                longitude=0.0,
            )
        )
        await session.flush()
        raise SeedPhaseError(PHASE_POPULATE, "injected populate failure")

    monkeypatch.setattr(seed, "phase_populate", _failing_populate)

    with pytest.raises(SeedPhaseError) as excinfo:
        await run_seed(database_url=sqlite_url, skip_redis=True)

    # The error names the failed phase (Requirement 2.2).
    assert excinfo.value.phase == PHASE_POPULATE

    # Drop + recreate ran, so the schema exists, but populate rolled back: no
    # partially-populated data is committed (Requirement 2.2).
    counts = await _table_counts(sqlite_url)
    assert counts == {"users": 0, "products": 0, "order_history": 0}


# --------------------------------------------------------------------------- #
# Redis demand-key flush coordination (Requirement 2.7)
# --------------------------------------------------------------------------- #
class _FakeGateway:
    """Records whether the demand-key flush was invoked."""

    def __init__(self) -> None:
        self.flush_calls = 0

    async def flush_demand_keys(self) -> int:
        self.flush_calls += 1
        return 3


async def test_redis_flush_invoked_when_not_skipped(sqlite_url, monkeypatch) -> None:
    """The non-skip path flushes the demand keys exactly once (Req 2.7)."""
    fake = _FakeGateway()
    monkeypatch.setattr("app.db.redis_gateway.get_gateway", lambda: fake)

    summary = await run_seed(database_url=sqlite_url, skip_redis=False)

    assert summary["users"] == 2
    assert fake.flush_calls == 1


async def test_redis_untouched_when_skip_redis(sqlite_url, monkeypatch) -> None:
    """The skip_redis path never touches Redis (Requirement 2.7)."""
    fake = _FakeGateway()
    monkeypatch.setattr("app.db.redis_gateway.get_gateway", lambda: fake)

    await run_seed(database_url=sqlite_url, skip_redis=True)

    assert fake.flush_calls == 0


# --------------------------------------------------------------------------- #
# Full SQLite smoke path (run_smoke) — double-run idempotence (Req 2.1)
# --------------------------------------------------------------------------- #
async def test_run_smoke_double_run_succeeds() -> None:
    """run_smoke seeds a throwaway SQLite DB twice with identical summaries."""
    summary = await run_smoke()
    assert summary["users"] == 2
    assert 5 <= summary["products"] <= 50
    assert summary["order_history"] >= 2
