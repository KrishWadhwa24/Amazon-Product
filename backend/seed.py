"""Seed script for the Amazon Edge-Return relational store and demand index.

Run with::

    python seed.py                 # seed the configured PostgreSQL + Redis
    python seed.py --smoke         # SQLite import/populate smoke check (no servers)
    python seed.py --skip-redis    # seed PostgreSQL only, skip the Redis flush

Requirement 2 (Seeding Strategy) drives the design. The script executes three
ordered phases and, on any phase failure, aborts the remaining phases, leaves no
partially-populated seed data committed to the Relational_Store, and exits with
a non-zero status naming the failed phase (Requirement 2.2):

1. **drop**     — drop all tables, idempotent whether or not they exist
                  (Requirement 2.1).
2. **recreate** — create the schema from ``Base.metadata``.
3. **populate** — insert the seed users, catalog, order history, hubs, and the
                  initial metric snapshot inside a single transaction so a
                  populate failure rolls back with nothing committed
                  (Requirements 2.2-2.6).

A fourth coordination step flushes the Redis demand keys so the Geospatial_Index
starts with zero demand entries referencing only seeded ASINs (Requirement 2.7).

Demo login credentials (plaintext, for the prototype only):

    Priya Sharma (Seller)  email: priya.sharma@example.com   password: priya
    Rahul Verma  (Buyer)   email: rahul.verma@example.com    password: rahul

Image handling: every seeded Product carries a placeholder ``image_url`` served
by the frontend (``/placeholder-product.svg``) and a NULL ``uploaded_image_path``
so the UI shows a demo picture until a real photo is uploaded later.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

# Importing the models package registers every entity on Base.metadata so the
# drop/recreate phases operate on the full schema from one metadata object.
from app.db.base import Base
from app.models import (
    ConditionGrade,
    Hub,
    MetricSnapshot,
    OrderHistory,
    Product,
    ResaleListing,
    ResaleStatus,
    User,
    UserRole,
)

# ---------------------------------------------------------------------------
# Phase identifiers (used in error messages and the non-zero exit, Req 2.2).
# ---------------------------------------------------------------------------
PHASE_DROP = "drop"
PHASE_RECREATE = "recreate"
PHASE_POPULATE = "populate"
PHASE_REDIS = "redis-flush"

# Demo credentials — plaintext documented here for the prototype only.
PRIYA_EMAIL = "priya.sharma@example.com"
PRIYA_PASSWORD = "priya"
RAHUL_EMAIL = "rahul.verma@example.com"
RAHUL_PASSWORD = "rahul"

# Placeholder image served by the frontend until a real photo is uploaded.
PLACEHOLDER_IMAGE = "/placeholder-product.svg"

# Placeholder "live condition" capture used for the seeded resale listing so the
# Split-Trust gallery has a secondary image until a real photo is uploaded.
PLACEHOLDER_CONDITION_IMAGE = "/placeholder-condition.svg"

# The two products that must exist in the catalog and Priya's order history
# (Requirement 2.6).
ASIN_SONY = "B09VLY3X5K"  # Sony WH-CH520 Wireless Headphones
ASIN_LEVIS = "B07L5G3X9M"  # Levi's T-Shirt

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class SeedPhaseError(RuntimeError):
    """Raised when a seed phase fails; carries the failed-phase name (Req 2.2)."""

    def __init__(self, phase: str, message: str) -> None:
        self.phase = phase
        super().__init__(f"[phase={phase}] {message}")


def hash_password(plaintext: str) -> str:
    """Return a bcrypt hash for ``plaintext`` (Requirement 1.2)."""
    return _pwd_context.hash(plaintext)


# ---------------------------------------------------------------------------
# Seed data builders (pure — no I/O).
# ---------------------------------------------------------------------------
def build_users() -> tuple[User, User,User]:
    """Build Priya (Seller) and Rahul (Buyer) per Requirements 2.3, 2.4."""
    priya = User(
        name="Priya Sharma",
        email=PRIYA_EMAIL,
        password_hash=hash_password(PRIYA_PASSWORD),
        role=UserRole.SELLER,
        latitude=12.9781,
        longitude=77.6389,
    )
    rahul = User(
        name="Rahul Verma",
        email=RAHUL_EMAIL,
        password_hash=hash_password(RAHUL_PASSWORD),
        role=UserRole.BUYER,
        latitude=12.9352,
        longitude=77.6271,
    )
    krish = User(
        name="Krishna Sharma",
        email="krishna.sharma@example.com",
        password_hash=hash_password("krishna"),
        role=UserRole.SELLER,
        latitude=12.9781,
        longitude=77.6389,
    )
    # Rahul's cart is intentionally left empty (Requirement 2.4): we create no
    # CartItem rows for him.
    return priya, rahul, krish


def build_products() -> list[Product]:
    """Build a valid 5-50 product catalog (Requirement 2.5).

    Includes the two required named products (Requirement 2.6). Each product has
    a unique non-empty ASIN, non-empty name, price > 0, rating in [0, 5],
    review_count >= 0, a non-null placeholder image_url, NULL uploaded_image_path,
    and estimated_reverse_logistics_cost >= 0.
    """
    # (asin, name, price, rating, review_count, est_reverse_logistics_cost)
    rows: list[tuple[str, str, str, float, int, str]] = [
        (ASIN_SONY, "Sony WH-CH520 Wireless Headphones", "4490.00", 4.3, 18234, "180.00"),
        (ASIN_LEVIS, "Levi's T-Shirt", "799.00", 4.1, 5421, "90.00"),
        ("B0C7KMP1N4", "boAt Rockerz 255 Pro+ Earphones", "1299.00", 4.0, 90211, "120.00"),
        ("B08CF3D7QR", "Echo Dot (5th Gen) Smart Speaker", "4499.00", 4.5, 64102, "150.00"),
        ("B09G9F5J7T", "Fire TV Stick 4K", "5999.00", 4.4, 88210, "140.00"),
        ("B07DJCN1234", "Wildcraft 44L Travel Backpack", "1799.00", 4.2, 12044, "110.00"),
        ("B0816J7B7C", "Logitech M331 Silent Mouse", "999.00", 4.5, 23310, "80.00"),
        ("B07HSCFZ5K", "Prestige Electric Kettle 1.5L", "1099.00", 4.3, 18760, "130.00"),
        ("B08L5W9K2P", "Milton Thermosteel Flask 1L", "899.00", 4.4, 9981, "95.00"),
        ("B07Q9MJZ5R", "Redmi Smart Band Pro", "2499.00", 4.0, 30122, "100.00"),
        ("B09XJK4F2D", "Amazon Basics AAA Batteries (24-pack)", "549.00", 4.6, 41200, "60.00"),
        ("B08T7P6N9V", "Noise ColorFit Pulse Smartwatch", "1799.00", 3.9, 52001, "115.00"),
    ]
    products: list[Product] = []
    for asin, name, price, rating, review_count, est_cost in rows:
        products.append(
            Product(
                asin=asin,
                name=name,
                price=Decimal(price),
                rating=rating,
                review_count=review_count,
                image_url=PLACEHOLDER_IMAGE,
                uploaded_image_path=None,
                estimated_reverse_logistics_cost=Decimal(est_cost),
            )
        )
    return products


def build_hubs() -> list[Hub]:
    """Build reverse-logistics dispatch hubs (Requirement 16 support)."""
    return [
        Hub(name="IND-BLR-01", latitude=12.9716, longitude=77.5946),
        Hub(name="IND-BLR-02", latitude=13.0358, longitude=77.5970),
    ]


# ---------------------------------------------------------------------------
# Phase functions.
# ---------------------------------------------------------------------------
async def phase_drop(engine) -> None:
    """Drop all tables, idempotent whether or not they exist (Requirement 2.1).

    ``drop_all`` with ``checkfirst=True`` (the default) issues drops only for
    tables that are present, so this succeeds on an empty database.
    """
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all, checkfirst=True)
    except Exception as exc:  # noqa: BLE001 - surfaced as a named phase failure
        raise SeedPhaseError(PHASE_DROP, f"failed to drop tables: {exc}") from exc


async def phase_recreate(engine) -> None:
    """Create the schema from ``Base.metadata`` (Requirement 2.1)."""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001
        raise SeedPhaseError(PHASE_RECREATE, f"failed to create schema: {exc}") from exc


async def phase_populate(session: AsyncSession) -> dict[str, int]:
    """Insert all seed rows in one transaction (Requirements 2.2-2.6).

    The caller wraps this in a single transaction and commits only after it
    returns, so any exception raised here rolls back with nothing committed
    (Requirement 2.2). Returns a small summary of inserted counts.
    """
    try:
        now = datetime.now(timezone.utc)

        priya, rahul, krish = build_users()
        products = build_products()
        hubs = build_hubs()

        session.add_all([priya, rahul,krish])
        session.add_all(products)
        session.add_all(hubs)
        # Flush to assign primary keys before wiring foreign keys.
        await session.flush()

        by_asin = {p.asin: p for p in products}

        # >= 2 past-dated OrderHistory rows for Priya, including the two required
        # products (Requirement 2.6). Levi's is > 7 days old so it is also
        # resale-eligible (Requirement 11.1) for the demo.
        order_history = [
            OrderHistory(
                user_id=priya.id,
                product_id=by_asin[ASIN_SONY].id,
                purchased_at=now - timedelta(days=3),
            ),
            OrderHistory(
                user_id=priya.id,
                product_id=by_asin[ASIN_LEVIS].id,
                purchased_at=now - timedelta(days=12),
            ),
            OrderHistory(
                user_id=priya.id,
                product_id=by_asin["B08CF3D7QR"].id,
                purchased_at=now - timedelta(days=30),
            ),
        ]
        
        krish_orders = [
                OrderHistory(
                    user_id=krish.id,
                    product_id=by_asin[ASIN_SONY].id,
                    purchased_at=now - timedelta(days=1),
                ),
                OrderHistory(
                    user_id=krish.id,
                    product_id=by_asin["B0816J7B7C"].id,  # Logitech Mouse
                    purchased_at=now - timedelta(days=20),
                ),
                OrderHistory(
                    user_id=krish.id,
                    product_id=by_asin["B09G9F5J7T"].id,  # Fire TV Stick
                    purchased_at=now - timedelta(days=45),
                ),
            ]

        session.add_all(krish_orders)
        session.add_all(order_history)
        await session.flush()

        # One ACTIVE resale listing so the "Local Verified Used Deals"
        # marketplace is demonstrable on first run (Requirement 12). It is
        # listed by Priya from her resale-eligible Levi's purchase; buyers can
        # browse, add to cart, and buy it. The condition image uses the
        # placeholder "live condition" capture until a real photo is uploaded.
        levis_order = order_history[1]
        session.add(
            ResaleListing(
                product_id=by_asin[ASIN_LEVIS].id,
                order_history_id=levis_order.id,
                seller_id=priya.id,
                status=ResaleStatus.ACTIVE,
                condition_grade=ConditionGrade.LIKE_NEW,
                resale_price=Decimal("499.00"),
                condition_image_url=PLACEHOLDER_CONDITION_IMAGE,
                listed_at=now - timedelta(days=1),
            )
        )

        # Initial admin metric snapshot (Requirements 13, 16): zero usage with a
        # non-zero total capacity so the KPI grid renders valid bounds.
        session.add(
            MetricSnapshot(
                cache_used=0,
                cache_total=50,
                reverse_logistics_saved=Decimal("0.00"),
                carbon_offset_index_kg=0.0,
                ngo_csr_credits=Decimal("0.00"),
                captured_at=now,
            )
        )

        await session.flush()
        return {
            "users": 3,
            "products": len(products),
            "order_history": len(order_history) + len(krish_orders),
            "hubs": len(hubs),
            "metric_snapshots": 1,
        }
    except SeedPhaseError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SeedPhaseError(PHASE_POPULATE, f"failed to populate seed data: {exc}") from exc


async def phase_flush_redis() -> int:
    """Flush demand keys so the Geospatial_Index starts empty (Requirement 2.7).

    Returns the number of demand keys removed. Raises :class:`SeedPhaseError`
    (phase ``redis-flush``) if Redis cannot be reached or the flush fails.
    """
    # Imported lazily so the relational-only / smoke paths never require redis.
    from app.db.redis_gateway import get_gateway

    try:
        gateway = get_gateway()
        return await gateway.flush_demand_keys()
    except Exception as exc:  # noqa: BLE001
        raise SeedPhaseError(PHASE_REDIS, f"failed to flush Redis demand keys: {exc}") from exc


# ---------------------------------------------------------------------------
# Orchestration.
# ---------------------------------------------------------------------------
async def run_seed(
    *,
    database_url: str | None = None,
    skip_redis: bool = False,
) -> dict[str, int]:
    """Run the ordered drop -> recreate -> populate (+ Redis flush) phases.

    Raises :class:`SeedPhaseError` on the first failing phase so the caller can
    report the phase name and exit non-zero (Requirement 2.2).
    """
    if database_url is None:
        from app.core.config import get_settings

        database_url = get_settings().db_url

    engine = create_async_engine(database_url, future=True)
    summary: dict[str, int] = {}
    try:
        # Phase 1: drop (idempotent).
        await phase_drop(engine)
        print(f"[{PHASE_DROP}] ok — existing tables dropped (idempotent)")

        # Phase 2: recreate schema.
        await phase_recreate(engine)
        print(f"[{PHASE_RECREATE}] ok — schema created from Base.metadata")

        # Phase 3: populate inside a single transaction. Commit only on success
        # so a failure leaves nothing committed (Requirement 2.2).
        sessionmaker_kwargs = {"bind": engine, "expire_on_commit": False}
        async with AsyncSession(**sessionmaker_kwargs) as session:
            try:
                summary = await phase_populate(session)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        print(
            f"[{PHASE_POPULATE}] ok — "
            + ", ".join(f"{k}={v}" for k, v in summary.items())
        )
    finally:
        await engine.dispose()

    # Phase 4: flush Redis demand keys (Requirement 2.7).
    if skip_redis:
        print(f"[{PHASE_REDIS}] skipped (--skip-redis)")
    else:
        deleted = await phase_flush_redis()
        print(f"[{PHASE_REDIS}] ok — {deleted} demand key(s) removed")

    return summary


async def run_smoke() -> dict[str, int]:
    """Run the full phase sequence against a throwaway SQLite database.

    Verifies the phase functions and seed data against a real (file-backed)
    engine without requiring PostgreSQL or Redis. Redis is skipped.
    """
    tmp_dir = tempfile.mkdtemp(prefix="edge_return_seed_smoke_")
    db_path = os.path.join(tmp_dir, "smoke.db")
    url = f"sqlite+aiosqlite:///{db_path}"
    print(f"[smoke] using temporary SQLite database at {db_path}")

    # Run twice to prove idempotence of drop on a pre-populated database
    # (Requirement 2.1: completes whether or not tables exist).
    first = await run_seed(database_url=url, skip_redis=True)
    print("[smoke] second run against the now-populated database...")
    second = await run_seed(database_url=url, skip_redis=True)
    assert first == second, "seed summary differed between runs"
    print("[smoke] both runs succeeded with identical summaries")
    return second


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed the Amazon Edge-Return stores.")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run a SQLite import/populate smoke check (no PostgreSQL/Redis needed).",
    )
    parser.add_argument(
        "--skip-redis",
        action="store_true",
        help="Seed the relational store only; skip flushing the Redis demand keys.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override the database URL (defaults to the configured DB_URL).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint. Returns a process exit code (0 ok, non-zero on failure)."""
    args = _parse_args(argv)
    try:
        if args.smoke:
            asyncio.run(run_smoke())
        else:
            asyncio.run(
                run_seed(database_url=args.database_url, skip_redis=args.skip_redis)
            )
    except SeedPhaseError as exc:
        # Requirement 2.2: abort with a non-zero exit naming the failed phase.
        print(f"SEED FAILED in phase '{exc.phase}': {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - graceful guard for connection issues
        print(
            "SEED FAILED: could not complete seeding. "
            f"Is PostgreSQL/Redis running and reachable? Details: {exc}",
            file=sys.stderr,
        )
        return 1

    print("Seeding completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
