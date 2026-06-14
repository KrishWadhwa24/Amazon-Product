"""Thin async Redis gateway for the inverted geospatial demand index.

Wraps the native Redis commands the demand index depends on
(``GEOADD`` / ``GEOSEARCH`` plus a timestamp sidecar hash) behind a small,
typed surface so the Demand Signal Service (task 9.1) and Matching Engine
(task 10.1) never touch the raw client.

Key schema (see design "Redis Inverted Geospatial Demand Index"):

* ``demand:{intent}:{asin}``      — GEO set, member = buyer id (Requirement 4.5)
* ``demand_ts:{intent}:{asin}``   — hash buyer_id -> epoch_ms (Requirement 5.3)

Any native command failure is surfaced as :class:`SignalStorageError` so callers
can honor Requirement 4.7: a signal that failed to write is never reported as
successfully stored.

The client is created lazily and memoized, so importing this module never
opens a connection or requires a running Redis server.
"""

from __future__ import annotations

from functools import lru_cache

from redis.asyncio import Redis
from redis.exceptions import RedisError


class SignalStorageError(RuntimeError):
    """Raised when a Redis demand-index command fails.

    Callers translate this into a failure response (Requirement 4.7) and must
    not report the demand signal as stored.
    """


@lru_cache
def get_redis_client() -> Redis:
    """Return the memoized async Redis client, created on first use.

    ``decode_responses=True`` yields ``str`` members and values rather than
    bytes, which keeps buyer ids and timestamps easy to work with.
    """
    from app.core.config import get_settings

    settings = get_settings()
    return Redis.from_url(settings.redis_url, decode_responses=True)


class RedisGateway:
    """Async wrapper over the native Redis commands the demand index needs."""

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def geo_add(self, key: str, lon: float, lat: float, member: str) -> None:
        """Add/overwrite ``member`` at ``(lon, lat)`` under ``key``.

        Wraps native ``GEOADD key lon lat member``. Re-adding the same member
        overwrites its coordinates, so at most one entry per buyer exists per
        key (Requirement 4.5). Raises :class:`SignalStorageError` if the command
        fails (Requirement 4.7).
        """
        try:
            await self._client.geoadd(key, (lon, lat, member))
        except RedisError as exc:  # pragma: no cover - exercised via stub in tests
            raise SignalStorageError(
                f"GEOADD failed for key {key!r} member {member!r}: {exc}"
            ) from exc

    async def geo_search(
        self, key: str, lon: float, lat: float, radius_km: float
    ) -> list[tuple[str, float]]:
        """Return ``(member, distance_km)`` pairs within ``radius_km`` of a point.

        Wraps native ``GEOSEARCH key FROMLONLAT lon lat BYRADIUS radius_km km
        ASC WITHDIST`` (Requirements 6.3, 6.4). Results are ordered nearest
        first; distances are kilometers as returned by Redis. Raises
        :class:`SignalStorageError` on command failure.
        """
        try:
            raw = await self._client.geosearch(
                key,
                longitude=lon,
                latitude=lat,
                radius=radius_km,
                unit="km",
                sort="ASC",
                withdist=True,
            )
        except RedisError as exc:  # pragma: no cover - exercised via stub in tests
            raise SignalStorageError(
                f"GEOSEARCH failed for key {key!r}: {exc}"
            ) from exc

        results: list[tuple[str, float]] = []
        for item in raw:
            # With WITHDIST, redis-py returns ``[member, distance]`` per hit.
            member, distance = item[0], item[1]
            results.append((member, float(distance)))
        return results

    async def hset_ts(self, key: str, member: str, epoch_ms: int) -> None:
        """Record the signal timestamp for ``member`` under ``key``.

        Wraps native ``HSET demand_ts:... member epoch_ms`` so the scoring tie
        break can order equal-score signals by earliest timestamp
        (Requirement 5.3). Raises :class:`SignalStorageError` on failure.
        """
        try:
            await self._client.hset(key, member, str(int(epoch_ms)))
        except RedisError as exc:  # pragma: no cover - exercised via stub in tests
            raise SignalStorageError(
                f"HSET failed for key {key!r} member {member!r}: {exc}"
            ) from exc

    async def hget_ts(self, key: str, member: str) -> int | None:
        """Return the recorded epoch-ms timestamp for ``member`` or ``None``."""
        try:
            value = await self._client.hget(key, member)
        except RedisError as exc:  # pragma: no cover - exercised via stub in tests
            raise SignalStorageError(
                f"HGET failed for key {key!r} member {member!r}: {exc}"
            ) from exc
        return int(value) if value is not None else None

    async def flush_demand_keys(self) -> int:
        """Delete every ``demand:*`` and ``demand_ts:*`` key; return the count.

        Used by the seed script so the Geospatial_Index starts with zero demand
        entries (Requirement 2.7). Raises :class:`SignalStorageError` on failure.
        """
        try:
            deleted = 0
            for pattern in ("demand:*", "demand_ts:*"):
                async for found in self._client.scan_iter(match=pattern):
                    await self._client.delete(found)
                    deleted += 1
            return deleted
        except RedisError as exc:  # pragma: no cover - exercised via stub in tests
            raise SignalStorageError(f"Flushing demand keys failed: {exc}") from exc


@lru_cache
def get_gateway() -> RedisGateway:
    """Return the memoized :class:`RedisGateway` bound to the shared client."""
    return RedisGateway(get_redis_client())


def get_redis() -> RedisGateway:
    """FastAPI dependency / accessor returning the shared Redis gateway."""
    return get_gateway()
