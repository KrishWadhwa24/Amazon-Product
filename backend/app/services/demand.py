"""Demand Signal Service — record buyer purchase intent (Requirement 4).

Buyers express purchase intent through four signal types — ``cart``, ``buynow``,
``wishlist``, and ``viewed`` — and each event is recorded into the Redis
inverted geospatial demand index so the Matching_Engine can later retrieve, for
any ASIN, every interested buyer and their location in a single geo query.

What this module does (task 9.1):

* Validates the buyer's coordinates *before* any Redis write — longitude in
  ``[-180, 180]`` and latitude in ``[-90, 90]``; absent or out-of-bounds
  coordinates raise :class:`~app.core.errors.InvalidLocationError` and produce
  no write (Requirement 4.6). The API maps this to ``400/422 INVALID_LOCATION``.
* On valid coordinates, writes the signal with the native geospatial add under
  ``demand:{intent}:{asin}`` (member = buyer id, re-adding overwrites so at most
  one entry per buyer exists per key) (Requirements 4.1–4.5), then records the
  signal timestamp under ``demand_ts:{intent}:{asin}`` for the scoring tie-break
  (Requirements 5.3).
* If the geospatial add fails, the underlying
  :class:`~app.db.redis_gateway.SignalStorageError` propagates so the API
  returns ``502 SIGNAL_NOT_RECORDED`` and the signal is **never** reported as
  stored (Requirement 4.7).

Scope note: this module records the signal only. Triggering the Matching_Engine
on a successful write is wired separately (task 10.1); building the HTTP
cart/wishlist/view endpoints is task 20.2. The validation helpers are pure and
importable so they can be property-tested in isolation (task 9.4).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Optional

from app.core.errors import InvalidLocationError
from app.db.redis_gateway import RedisGateway, get_gateway

__all__ = [
    "VALID_INTENTS",
    "LON_MIN",
    "LON_MAX",
    "LAT_MIN",
    "LAT_MAX",
    "demand_key",
    "demand_ts_key",
    "is_valid_location",
    "validate_location",
    "validate_intent",
    "SignalResult",
    "record_signal",
]


# The four recognized demand-signal intents. Kept consistent with the scoring
# core (``app.core.scoring.DEMAND_SCORES``) and the ``demand:{intent}:{asin}``
# Redis key schema (Requirements 4.1–4.4).
VALID_INTENTS: frozenset[str] = frozenset({"cart", "buynow", "wishlist", "viewed"})

# Valid geographic bounds for buyer coordinates (Requirement 4.6).
LON_MIN: float = -180.0
LON_MAX: float = 180.0
LAT_MIN: float = -90.0
LAT_MAX: float = 90.0


def demand_key(intent: str, asin: str) -> str:
    """Return the geospatial demand key ``demand:{intent}:{asin}``.

    This is the single source of truth for the demand key format
    (Requirements 4.1–4.5); both the writer here and the Matching_Engine reader
    derive their keys from it so the two never drift apart.
    """
    return f"demand:{intent}:{asin}"


def demand_ts_key(intent: str, asin: str) -> str:
    """Return the timestamp sidecar key ``demand_ts:{intent}:{asin}``.

    The sidecar hash records each signal's recorded time so equal-score signals
    can be tie-broken by earliest timestamp during scoring (Requirement 5.3).
    """
    return f"demand_ts:{intent}:{asin}"


def is_valid_location(lon: object, lat: object) -> bool:
    """Return ``True`` iff ``(lon, lat)`` is a valid buyer location.

    A location is valid when both coordinates are present, finite, and within
    bounds: longitude in ``[-180, 180]`` and latitude in ``[-90, 90]``
    (Requirement 4.6). Absent (``None``), non-numeric, ``NaN``, or infinite
    values are invalid. This predicate is pure and side-effect free so it can be
    property-tested directly (task 9.4).
    """
    if lon is None or lat is None:
        return False
    # ``bool`` is an ``int`` subclass; reject it so True/False aren't treated as
    # coordinates.
    if isinstance(lon, bool) or isinstance(lat, bool):
        return False
    try:
        lon_f = float(lon)
        lat_f = float(lat)
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(lon_f) and math.isfinite(lat_f)):
        return False
    return LON_MIN <= lon_f <= LON_MAX and LAT_MIN <= lat_f <= LAT_MAX


def validate_location(lon: object, lat: object) -> tuple[float, float]:
    """Return ``(lon, lat)`` as floats when valid, else raise.

    Raises :class:`~app.core.errors.InvalidLocationError` when the coordinates
    are absent or out of bounds (Requirement 4.6). Callers invoke this *before*
    any Redis write so a rejected location produces no Geospatial_Index entry.
    """
    if not is_valid_location(lon, lat):
        raise InvalidLocationError(lon, lat)
    return float(lon), float(lat)  # type: ignore[arg-type]


def validate_intent(intent: str) -> str:
    """Return ``intent`` when it is one of the recognized demand intents.

    Raises :class:`ValueError` for any value outside :data:`VALID_INTENTS` so a
    malformed key (``demand:{intent}:{asin}``) is never written.
    """
    if intent not in VALID_INTENTS:
        raise ValueError(
            f"unknown demand intent {intent!r}; expected one of "
            f"{sorted(VALID_INTENTS)}"
        )
    return intent


@dataclass(frozen=True)
class SignalResult:
    """Outcome of a successfully recorded demand signal.

    Returned only after both the geospatial add and the timestamp write
    succeed; if recording fails, no result is produced and the failure
    propagates (Requirement 4.7).

    Attributes:
        intent: The demand intent (``cart``/``buynow``/``wishlist``/``viewed``).
        asin: The product ASIN the signal targets.
        buyer_id: The buyer identifier stored as the geo-set member.
        key: The ``demand:{intent}:{asin}`` key written.
        lon: The validated longitude stored for the buyer.
        lat: The validated latitude stored for the buyer.
        recorded_at_ms: The epoch-millisecond timestamp recorded for tie-breaks.
    """

    intent: str
    asin: str
    buyer_id: str
    key: str
    lon: float
    lat: float
    recorded_at_ms: int


async def record_signal(
    intent: str,
    asin: str,
    buyer_id: object,
    lon: object,
    lat: object,
    *,
    gateway: Optional[RedisGateway] = None,
    recorded_at_ms: Optional[int] = None,
) -> SignalResult:
    """Record a buyer demand signal in the geospatial index (Requirement 4).

    Validates the coordinates first; on valid input performs the native
    geospatial add under ``demand:{intent}:{asin}`` (member = ``buyer_id``,
    overwriting any prior entry for that buyer so at most one entry exists per
    buyer per key — Requirement 4.5) and records the signal timestamp under
    ``demand_ts:{intent}:{asin}`` (Requirement 5.3).

    Args:
        intent: One of ``cart``, ``buynow``, ``wishlist``, ``viewed``.
        asin: The product ASIN the buyer signalled intent for.
        buyer_id: The buyer identifier; stored as the geo-set member (str).
        lon: The buyer's longitude; must be in ``[-180, 180]``.
        lat: The buyer's latitude; must be in ``[-90, 90]``.
        gateway: Optional Redis gateway override (defaults to the shared
            gateway); injected in tests.
        recorded_at_ms: Optional epoch-ms timestamp override (defaults to the
            current time); injected in tests for determinism.

    Returns:
        A :class:`SignalResult` describing the stored entry.

    Raises:
        InvalidLocationError: If the coordinates are absent or out of bounds;
            no Redis write occurs (Requirement 4.6).
        ValueError: If ``intent`` is not a recognized demand intent.
        SignalStorageError: If the native geospatial add fails; the signal is
            not reported as stored (Requirement 4.7).
    """
    validate_intent(intent)
    # Validate coordinates BEFORE any write so a rejected location leaves the
    # Geospatial_Index untouched (Requirement 4.6).
    valid_lon, valid_lat = validate_location(lon, lat)

    member = str(buyer_id)
    key = demand_key(intent, asin)
    ts_key = demand_ts_key(intent, asin)
    gw = gateway if gateway is not None else get_gateway()

    # GEOADD first: if it fails, SignalStorageError propagates and we never
    # reach the timestamp write or report success (Requirement 4.7).
    await gw.geo_add(key, valid_lon, valid_lat, member)

    epoch_ms = recorded_at_ms if recorded_at_ms is not None else int(time.time() * 1000)
    await gw.hset_ts(ts_key, member, epoch_ms)

    return SignalResult(
        intent=intent,
        asin=asin,
        buyer_id=member,
        key=key,
        lon=valid_lon,
        lat=valid_lat,
        recorded_at_ms=epoch_ms,
    )
