"""Pure matching core: haversine distance and nearest-candidate selection.

This module is the side-effect-free heart of the Matching_Engine
(Requirement 6). It contains no I/O: no database queries, no Redis access, no
clock reads. Everything it needs is passed in as plain value objects, which
makes it trivially unit- and property-testable (Properties 8 and 9) and lets
the I/O shell (task 10.1) adapt SQLAlchemy rows / Redis results into these
shapes before calling in.

Design references:
- Matching algorithm and `select_match` pipeline: design.md "Matching Engine"
  and "Matching Engine and Demand Scoring Design".
- Requirements 6.1, 6.2, 6.3, 6.4, 6.8.

Coordinate convention
----------------------
A geographic position is represented by :class:`Point`, an explicit
``(lat, lon)`` value object (latitude first, longitude second). Using a named
type rather than a bare tuple removes any ambiguity about ordering — Redis
``GEOADD`` takes ``lon, lat`` while most map libraries use ``lat, lon``, so the
shell is responsible for constructing :class:`Point` correctly from its source.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from app.models.enums import ReturnStatus

# Match_Radius: the maximum eligible distance, 20 kilometers (Requirement 6.4,
# 6.8; glossary "Match_Radius"). A candidate qualifies when its rounded
# distance is less than or equal to this value, so exactly 20.00 km is eligible.
MATCH_RADIUS_KM: float = 20.0

# Mean Earth radius in kilometers used by the great-circle (haversine)
# computation. 6371.0088 km is the IUGG mean radius; documented here so the
# property test (task 6.4) can reproduce the exact same formula.
EARTH_RADIUS_KM: float = 6371.0088


@dataclass(frozen=True)
class Point:
    """An immutable geographic coordinate.

    Attributes:
        lat: Latitude in decimal degrees, in [-90, 90].
        lon: Longitude in decimal degrees, in [-180, 180].
    """

    lat: float
    lon: float


@dataclass(frozen=True)
class Candidate:
    """A plain value object describing one ReturnOrder candidate.

    The I/O shell (task 10.1) builds these from ``ReturnOrder`` rows joined to
    their seller's coordinates. Keeping this decoupled from SQLAlchemy lets the
    selection logic stay pure and fully property-testable.

    Attributes:
        return_order_id: Identifier of the source ReturnOrder.
        seller_id: Identifier of the seller who initiated the return; compared
            against the buyer's id for the self-match exclusion (Req 6.2).
        seller_point: The seller's geographic location (Req 6.3 distance).
        asin: The returned product's ASIN; must equal the buyer's ASIN (Req 6.2).
        status: The ReturnOrder status; only ``SCANNING`` is eligible (Req 6.2).
            Accepts a :class:`ReturnStatus` or its string value.
        expires_at: The end of the 48-hour scanner window; must be strictly
            later than the buyer's ``now`` to be eligible (Req 6.2) and is the
            tie-breaker (earliest first) when distances are equal (Req 6.4).
    """

    return_order_id: int
    seller_id: int
    seller_point: Point
    asin: str
    status: ReturnStatus | str
    expires_at: datetime


@dataclass(frozen=True)
class Buyer:
    """A plain value object describing the buyer that produced a demand signal.

    Attributes:
        id: The buyer's identifier (for the self-match exclusion, Req 6.2).
        point: The buyer's geographic location (Req 6.3 distance).
        asin: The ASIN the demand signal is for (Req 6.1).
        now: The reference "current time" used for the non-expired check
            (Req 6.2). Passed in rather than read from the clock to keep the
            function pure and deterministic.
    """

    id: int
    point: Point
    asin: str
    now: datetime


@dataclass(frozen=True)
class MatchSelection:
    """The result of :func:`select_match`: the chosen candidate + its distance.

    Attributes:
        candidate: The selected nearest eligible :class:`Candidate`.
        distance_km: The great-circle distance to that candidate's seller, in
            kilometers rounded to two decimal places (Req 6.3).
    """

    candidate: Candidate
    distance_km: float


def haversine_km(point_a: Point, point_b: Point) -> float:
    """Return the great-circle distance between two points in kilometers.

    Uses the haversine formula on a sphere of radius :data:`EARTH_RADIUS_KM`.
    The result is rounded to two decimal places to match the precision the
    Matching_Engine stores as ``distance_km`` (Requirement 6.3).

    Args:
        point_a: The first coordinate.
        point_b: The second coordinate.

    Returns:
        The distance in kilometers, rounded to 2 decimals. The distance from a
        point to itself is ``0.0``.
    """
    lat1 = math.radians(point_a.lat)
    lat2 = math.radians(point_b.lat)
    dlat = math.radians(point_b.lat - point_a.lat)
    dlon = math.radians(point_b.lon - point_a.lon)

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    # Clamp to [0, 1] to guard against tiny floating-point overshoot before sqrt.
    c = 2 * math.atan2(math.sqrt(min(1.0, a)), math.sqrt(max(0.0, 1.0 - a)))
    return round(EARTH_RADIUS_KM * c, 2)


def _is_eligible(candidate: Candidate, buyer: Buyer) -> bool:
    """Return True when ``candidate`` passes the Req 6.2 filter for ``buyer``.

    Eligibility requires all of:
    - status is SCANNING,
    - the window is still open (``expires_at`` strictly later than ``now``),
    - the candidate's ASIN matches the buyer's ASIN, and
    - the candidate's seller is not the buyer (self-match exclusion).
    """
    return (
        candidate.status == ReturnStatus.SCANNING
        and candidate.expires_at > buyer.now
        and candidate.asin == buyer.asin
        and candidate.seller_id != buyer.id
    )


def select_match(candidates: list[Candidate], buyer: Buyer) -> MatchSelection | None:
    """Select the best ReturnOrder candidate for a buyer's demand signal.

    Pure implementation of the Matching_Engine selection (Requirements 6.1–6.4,
    6.8):

    1. Filter to candidates that are SCANNING, non-expired, share the buyer's
       ASIN, and belong to a different seller (Req 6.2).
    2. Compute the haversine distance to each, rounded to 2 decimals (Req 6.3).
    3. Keep only those within :data:`MATCH_RADIUS_KM` (``<= 20.0`` km;
       exactly 20.00 km qualifies — Req 6.4, 6.8).
    4. Select the smallest distance, breaking ties by earliest ``expires_at``
       (Req 6.4).
    5. Return ``None`` when nothing qualifies.

    Args:
        candidates: Candidate ReturnOrders to consider (any statuses/ASINs;
            filtering happens here).
        buyer: The buyer that produced the demand signal.

    Returns:
        A :class:`MatchSelection` for the chosen candidate, or ``None`` when no
        candidate is eligible or all eligible candidates lie beyond the radius.
    """
    eligible: list[MatchSelection] = []
    for candidate in candidates:
        if not _is_eligible(candidate, buyer):
            continue
        distance_km = haversine_km(buyer.point, candidate.seller_point)
        if distance_km <= MATCH_RADIUS_KM:
            eligible.append(MatchSelection(candidate=candidate, distance_km=distance_km))

    if not eligible:
        return None

    # Smallest distance wins; earliest expires_at breaks ties (Req 6.4).
    return min(
        eligible,
        key=lambda selection: (selection.distance_km, selection.candidate.expires_at),
    )
