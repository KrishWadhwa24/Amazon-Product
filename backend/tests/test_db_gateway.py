"""Tests for the DB session plumbing and Redis gateway (task 1.2).

These cover the gateway's command translation, per-buyer overwrite semantics,
``GEOSEARCH WITHDIST`` parsing, and the Requirement 4.7 failure surface
(``SignalStorageError``) using an in-memory async stub so no running Redis or
PostgreSQL server is required.
"""

from __future__ import annotations

import inspect

import pytest
from redis.exceptions import RedisError

from app.db import (
    Base,
    RedisGateway,
    SignalStorageError,
    get_redis,
    get_session,
)


class FakeRedis:
    """Minimal in-memory async double mimicking the redis-py async API.

    Implements just the commands the gateway uses, plus a ``fail`` switch to
    simulate native command failures for the Requirement 4.7 path.
    """

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.geo: dict[str, dict[str, tuple[float, float]]] = {}
        self.hashes: dict[str, dict[str, str]] = {}

    async def geoadd(self, key, values):
        if self.fail:
            raise RedisError("boom")
        lon, lat, member = values
        # Overwrite any prior entry for this member under this key.
        self.geo.setdefault(key, {})[member] = (lon, lat)

    async def geosearch(self, key, *, longitude, latitude, radius, unit, sort, withdist):
        if self.fail:
            raise RedisError("boom")
        # Return stored members with a fixed stub distance (km), nearest-first.
        members = self.geo.get(key, {})
        return [[member, 1.23] for member in members]

    async def hset(self, key, field, value):
        if self.fail:
            raise RedisError("boom")
        self.hashes.setdefault(key, {})[field] = value

    async def hget(self, key, field):
        if self.fail:
            raise RedisError("boom")
        return self.hashes.get(key, {}).get(field)

    async def scan_iter(self, match):
        prefix = match.rstrip("*")
        for key in list(self.geo) + list(self.hashes):
            if key.startswith(prefix):
                yield key

    async def delete(self, key):
        self.geo.pop(key, None)
        self.hashes.pop(key, None)


def test_base_is_declarative_with_metadata() -> None:
    """The declarative Base exposes a MetaData registry for schema creation."""
    assert hasattr(Base, "metadata")


def test_get_session_is_async_generator_dependency() -> None:
    """get_session is an async-generator FastAPI dependency."""
    assert inspect.isasyncgenfunction(get_session)


def test_get_redis_returns_shared_gateway() -> None:
    """get_redis yields a RedisGateway and is memoized (lazy, no connection)."""
    gw = get_redis()
    assert isinstance(gw, RedisGateway)
    assert get_redis() is gw


async def test_geo_add_overwrites_member() -> None:
    """Re-adding the same member overwrites its coordinates (Requirement 4.5)."""
    fake = FakeRedis()
    gw = RedisGateway(fake)
    await gw.geo_add("demand:cart:ASIN1", 77.6, 12.9, "buyer-1")
    await gw.geo_add("demand:cart:ASIN1", 10.0, 20.0, "buyer-1")
    assert fake.geo["demand:cart:ASIN1"] == {"buyer-1": (10.0, 20.0)}


async def test_geo_search_parses_member_and_distance() -> None:
    """geo_search returns (member, distance_km) tuples with float distances."""
    fake = FakeRedis()
    gw = RedisGateway(fake)
    await gw.geo_add("demand:cart:ASIN1", 77.6, 12.9, "buyer-1")
    results = await gw.geo_search("demand:cart:ASIN1", 77.6, 12.9, 20.0)
    assert results == [("buyer-1", 1.23)]


async def test_hset_and_hget_ts_roundtrip() -> None:
    """Timestamp sidecar stores and reads back epoch-ms as an int."""
    fake = FakeRedis()
    gw = RedisGateway(fake)
    await gw.hset_ts("demand_ts:cart:ASIN1", "buyer-1", 1700000000000)
    assert await gw.hget_ts("demand_ts:cart:ASIN1", "buyer-1") == 1700000000000
    assert await gw.hget_ts("demand_ts:cart:ASIN1", "absent") is None


async def test_flush_demand_keys_removes_demand_namespaces() -> None:
    """flush_demand_keys clears demand:* and demand_ts:* keys (Requirement 2.7)."""
    fake = FakeRedis()
    gw = RedisGateway(fake)
    await gw.geo_add("demand:cart:ASIN1", 77.6, 12.9, "buyer-1")
    await gw.hset_ts("demand_ts:cart:ASIN1", "buyer-1", 1)
    deleted = await gw.flush_demand_keys()
    assert deleted == 2
    assert fake.geo == {} and fake.hashes == {}


async def test_geo_add_failure_raises_signal_storage_error() -> None:
    """A failed GEOADD surfaces as SignalStorageError (Requirement 4.7)."""
    gw = RedisGateway(FakeRedis(fail=True))
    with pytest.raises(SignalStorageError):
        await gw.geo_add("demand:cart:ASIN1", 77.6, 12.9, "buyer-1")
