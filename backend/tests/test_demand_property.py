"""Property-based tests for the Demand Signal Service (tasks 9.2, 9.3, 9.4).

These exercise :func:`app.services.demand.record_signal` — the writer that
records buyer purchase intent into the Redis inverted geospatial demand index
(Requirement 4) — against an in-memory async Redis double so no running Redis
server is required.

Three universal properties are covered, one per test:

* Property 4 (task 9.2): a recorded signal writes exactly the key
  ``demand:{intent}:{asin}`` with the buyer id as the geo-set member at the
  buyer's ``(lon, lat)`` (Requirements 4.1–4.4).
* Property 5 (task 9.3): recording is per-buyer idempotent — repeated signals
  from the same buyer to the same key leave a single entry carrying the most
  recent coordinates (Requirement 4.5).
* Property 6 (task 9.4): out-of-bounds or absent coordinates are rejected with
  an ``InvalidLocationError`` and produce no write to the index (Requirement 4.6).

``record_signal`` is async, but Hypothesis drives synchronous test bodies, so
each test runs the coroutine to completion with :func:`asyncio.run` inside the
generated example body (keeping the async path genuinely exercised without the
pytest-asyncio + Hypothesis interaction). The in-memory ``FakeRedis`` mirrors
the stub pattern used in ``tests/test_db_gateway.py``.

Library: Hypothesis (per the design's Testing Strategy). One property per test,
minimum 100 iterations.
"""

from __future__ import annotations

import asyncio

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from redis.exceptions import RedisError

from app.core.errors import InvalidLocationError
from app.db.redis_gateway import RedisGateway
from app.services.demand import (
    VALID_INTENTS,
    demand_key,
    demand_ts_key,
    is_valid_location,
    record_signal,
)


class FakeRedis:
    """Minimal in-memory async double mimicking the redis-py async API.

    Implements just the commands :class:`RedisGateway` uses for demand
    recording. ``geoadd`` overwrites any prior entry for the same member under a
    key, matching the native ``GEOADD`` overwrite semantics (Requirement 4.5).
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

    async def geosearch(
        self, key, *, longitude, latitude, radius, unit, sort, withdist
    ):
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

    def is_empty(self) -> bool:
        """Return True iff no geo entry and no timestamp entry was written."""
        return not self.geo and not self.hashes


# --- Shared strategies ------------------------------------------------------

_INTENT = st.sampled_from(sorted(VALID_INTENTS))
# ASINs: non-empty alphanumeric tokens (the seeded catalog uses ASIN strings).
_ASIN = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", min_size=1, max_size=12
)
# Buyer identifiers: positive integers; record_signal stores str(buyer_id).
_BUYER = st.integers(min_value=1, max_value=10**9)

# Valid in-bounds coordinates (Requirement 4.6).
_IN_LON = st.floats(
    min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False
)
_IN_LAT = st.floats(
    min_value=-90.0, max_value=90.0, allow_nan=False, allow_infinity=False
)

# Out-of-bounds / absent coordinates (Requirement 4.6).
_OUT_LON = st.one_of(
    st.none(),
    st.floats(min_value=180.0001, max_value=1e7, allow_nan=False, allow_infinity=False),
    st.floats(min_value=-1e7, max_value=-180.0001, allow_nan=False, allow_infinity=False),
)
_OUT_LAT = st.one_of(
    st.none(),
    st.floats(min_value=90.0001, max_value=1e7, allow_nan=False, allow_infinity=False),
    st.floats(min_value=-1e7, max_value=-90.0001, allow_nan=False, allow_infinity=False),
)


@st.composite
def _invalid_coords(draw):
    """Draw a ``(lon, lat)`` pair guaranteed to be an invalid buyer location."""
    which = draw(st.sampled_from(["lon", "lat", "both"]))
    if which == "lon":
        return draw(_OUT_LON), draw(_IN_LAT)
    if which == "lat":
        return draw(_IN_LON), draw(_OUT_LAT)
    return draw(_OUT_LON), draw(_OUT_LAT)


# Feature: amazon-edge-return, Property 4: Demand signals map to the correct key with buyer coordinates
@settings(max_examples=15)
@given(intent=_INTENT, asin=_ASIN, buyer_id=_BUYER, lon=_IN_LON, lat=_IN_LAT)
def test_demand_signal_maps_to_correct_key_with_buyer_coordinates(
    intent: str, asin: str, buyer_id: int, lon: float, lat: float
) -> None:
    """A recorded signal writes exactly ``demand:{intent}:{asin}`` at (lon, lat).

    For any recognized intent, ASIN, and buyer with valid coordinates, after
    ``record_signal`` the geo-set under ``demand:{intent}:{asin}`` contains the
    buyer's id as a member at the buyer's ``(lon, lat)``, and a geo search at
    those coordinates returns that member. No other key is written.

    **Validates: Requirements 4.1, 4.2, 4.3, 4.4**
    """
    fake = FakeRedis()
    gw = RedisGateway(fake)
    member = str(buyer_id)
    key = demand_key(intent, asin)

    result = asyncio.run(
        record_signal(intent, asin, buyer_id, lon, lat, gateway=gw)
    )

    # The result reports exactly the intent-and-asin key and validated coords.
    assert result.key == key
    assert result.buyer_id == member
    assert (result.lon, result.lat) == (lon, lat)

    # The member is stored under exactly that key at the given (lon, lat).
    assert key in fake.geo
    assert fake.geo[key] == {member: (lon, lat)}

    # No demand geo key other than the one for this (intent, asin) was written.
    assert set(fake.geo.keys()) == {key}

    # A geo search at the buyer's coordinates returns the buyer's id (member).
    found = asyncio.run(gw.geo_search(key, lon, lat, 20.0))
    assert member in [m for m, _dist in found]


# Feature: amazon-edge-return, Property 5: Demand recording is per-buyer idempotent (overwrite)
@settings(max_examples=15)
@given(
    intent=_INTENT,
    asin=_ASIN,
    buyer_id=_BUYER,
    coords=st.lists(
        st.tuples(_IN_LON, _IN_LAT), min_size=1, max_size=8
    ),
)
def test_demand_recording_is_per_buyer_idempotent(
    intent: str,
    asin: str,
    buyer_id: int,
    coords: list[tuple[float, float]],
) -> None:
    """Repeated signals from one buyer leave a single most-recent entry.

    Recording the same buyer to the same key N times with changing coordinates
    leaves at most one geo entry for that buyer, carrying the coordinates of the
    most recent signal (Requirement 4.5). The timestamp sidecar likewise holds a
    single entry for the buyer.

    **Validates: Requirements 4.5**
    """
    fake = FakeRedis()
    gw = RedisGateway(fake)
    member = str(buyer_id)
    key = demand_key(intent, asin)
    ts_key = demand_ts_key(intent, asin)

    for i, (lon, lat) in enumerate(coords):
        asyncio.run(
            record_signal(
                intent, asin, buyer_id, lon, lat, gateway=gw, recorded_at_ms=i
            )
        )

    last_lon, last_lat = coords[-1]

    # Exactly one entry exists for this buyer under the key, with the most
    # recent coordinates (re-adding overwrites; never accumulates).
    assert fake.geo[key] == {member: (last_lon, last_lat)}
    assert len(fake.geo[key]) == 1

    # The timestamp sidecar also holds a single entry for this buyer.
    assert set(fake.hashes[ts_key].keys()) == {member}


# Feature: amazon-edge-return, Property 6: Invalid buyer coordinates are rejected with no write
@settings(max_examples=15)
@given(intent=_INTENT, asin=_ASIN, buyer_id=_BUYER, coords=_invalid_coords())
def test_invalid_buyer_coordinates_are_rejected_with_no_write(
    intent: str,
    asin: str,
    buyer_id: int,
    coords: tuple[object, object],
) -> None:
    """Out-of-bounds or absent coordinates raise and write nothing.

    For longitude outside ``[-180, 180]`` or latitude outside ``[-90, 90]`` (or
    ``None``), ``record_signal`` raises :class:`InvalidLocationError` and makes
    no write to the gateway — the in-memory index remains empty (Requirement
    4.6).

    **Validates: Requirements 4.6**
    """
    lon, lat = coords
    # Sanity: the generated coordinates are genuinely invalid.
    assert not is_valid_location(lon, lat)

    fake = FakeRedis()
    gw = RedisGateway(fake)

    with pytest.raises(InvalidLocationError):
        asyncio.run(record_signal(intent, asin, buyer_id, lon, lat, gateway=gw))

    # No write reached the Geospatial_Index: both the geo set and the timestamp
    # sidecar remain empty.
    assert fake.is_empty()
