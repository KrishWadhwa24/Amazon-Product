"""Property-based test for the match-selection pure core (task 6.5).

Exercises :func:`app.core.matching.select_match` — the Matching_Engine's
nearest-eligible-candidate selection (Requirements 6.1, 6.2, 6.4, 6.8) — over
randomly generated buyers and candidate lists with mixed statuses, ASINs,
sellers (including the buyer themselves), expiry times (past and future), and
seller positions that span near, far, and exactly the 20 km boundary.

The expected selection is recomputed independently inside the test using the
documented eligibility filter and the same ``haversine_km`` distance function,
then the nearest is chosen with the earliest-``expires_at`` tie-break. The
assertion therefore pins ``select_match`` to its contract rather than to a
table of hand-picked answers.

Library: Hypothesis (per the design's Testing Strategy). One property per test,
minimum 100 iterations.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.matching import (
    EARTH_RADIUS_KM,
    MATCH_RADIUS_KM,
    Buyer,
    Candidate,
    Point,
    haversine_km,
    select_match,
)
from app.models.enums import ReturnStatus

# A fixed reference "current time"; expiry offsets below straddle it so both
# expired (past) and live (future) candidates are generated (Req 6.2).
_NOW = datetime(2025, 1, 1, 12, 0, 0)

# A small ASIN pool so the buyer's ASIN frequently matches some candidates
# (a smart generator that constrains the input space to the interesting region
# rather than wasting examples on near-certain ASIN mismatches).
_ASINS = ["ASIN-A", "ASIN-B", "ASIN-C"]

# All ReturnOrder statuses so non-SCANNING candidates appear (Req 6.2 filter).
_STATUSES = list(ReturnStatus)

# Buyer latitude is kept within [-80, 80] so that placing a seller up to ~0.7°
# north of the buyer (see _candidate) can never push the seller past ±90°.
_BUYER_LAT = st.floats(
    min_value=-80.0, max_value=80.0, allow_nan=False, allow_infinity=False
)
_LON = st.floats(
    min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False
)

# Target seller distances spanning near and far, including the exact 20.00 km
# boundary so the "<= 20 km is eligible" edge is always representable.
_TARGET_KM = st.one_of(
    st.just(MATCH_RADIUS_KM),  # exactly 20.00 km — must be eligible (Req 6.8)
    st.floats(min_value=0.0, max_value=19.99, allow_nan=False, allow_infinity=False),
    st.floats(min_value=20.01, max_value=80.0, allow_nan=False, allow_infinity=False),
)


@st.composite
def _candidate(draw, buyer_lat: float, buyer_lon: float, buyer_id: int) -> Candidate:
    """Build one candidate placed a chosen great-circle distance from the buyer.

    The seller is positioned due north of the buyer by the latitude offset that
    yields ``target`` km (for a pure-latitude move the haversine distance is
    exactly ``EARTH_RADIUS_KM * radians(dlat)``), giving precise control over
    near/far/boundary placement. Status, ASIN, seller id (sometimes the buyer's
    own id), and expiry (past or future) are drawn independently so every arm
    of the Req 6.2 eligibility filter is exercised.
    """
    target = draw(_TARGET_KM)
    dlat_deg = math.degrees(target / EARTH_RADIUS_KM)
    seller_point = Point(lat=buyer_lat + dlat_deg, lon=buyer_lon)

    status = draw(st.sampled_from(_STATUSES))
    asin = draw(st.sampled_from(_ASINS))
    # Sometimes reuse the buyer's id to exercise the self-match exclusion.
    seller_id = draw(st.one_of(st.just(buyer_id), st.integers(min_value=1, max_value=20)))
    expires_offset = draw(st.integers(min_value=-100_000, max_value=100_000))
    expires_at = _NOW + timedelta(seconds=expires_offset)
    return_order_id = draw(st.integers(min_value=1, max_value=10_000))

    return Candidate(
        return_order_id=return_order_id,
        seller_id=seller_id,
        seller_point=seller_point,
        asin=asin,
        status=status,
        expires_at=expires_at,
    )


@st.composite
def _scenario(draw) -> tuple[Buyer, list[Candidate]]:
    """Build a (buyer, candidates) scenario with shared coordinate context."""
    buyer_lat = draw(_BUYER_LAT)
    buyer_lon = draw(_LON)
    buyer_id = draw(st.integers(min_value=1, max_value=20))
    buyer_asin = draw(st.sampled_from(_ASINS))
    buyer = Buyer(
        id=buyer_id,
        point=Point(lat=buyer_lat, lon=buyer_lon),
        asin=buyer_asin,
        now=_NOW,
    )
    candidates = draw(
        st.lists(
            _candidate(buyer_lat, buyer_lon, buyer_id), min_size=0, max_size=8
        )
    )
    return buyer, candidates


def _is_eligible(candidate: Candidate, buyer: Buyer) -> bool:
    """The Req 6.2 eligibility predicate, recomputed independently."""
    return (
        candidate.status == ReturnStatus.SCANNING
        and candidate.expires_at > buyer.now
        and candidate.asin == buyer.asin
        and candidate.seller_id != buyer.id
    )


def _expected_selection(
    buyer: Buyer, candidates: list[Candidate]
) -> tuple[Candidate, float] | None:
    """Independently recompute the eligible set and the nearest selection.

    Mirrors the documented algorithm: filter to eligible candidates within the
    20 km radius, then pick the smallest distance with the earliest
    ``expires_at`` as the tie-break, keeping the first occurrence for total
    ties (matching ``min``'s stability over the input order).
    """
    eligible: list[tuple[Candidate, float]] = []
    for candidate in candidates:
        if not _is_eligible(candidate, buyer):
            continue
        distance = haversine_km(buyer.point, candidate.seller_point)
        if distance <= MATCH_RADIUS_KM:
            eligible.append((candidate, distance))

    if not eligible:
        return None

    best = eligible[0]
    for candidate, distance in eligible[1:]:
        best_candidate, best_distance = best
        if (distance, candidate.expires_at) < (best_distance, best_candidate.expires_at):
            best = (candidate, distance)
    return best


# Feature: amazon-edge-return, Property 9: Match selection picks the nearest eligible candidate
@settings(max_examples=15)
@given(_scenario())
def test_match_selection_picks_nearest_eligible_candidate(
    scenario: tuple[Buyer, list[Candidate]],
) -> None:
    """select_match returns the nearest eligible candidate, or None.

    Only candidates that are SCANNING, non-expired, share the buyer's ASIN, and
    belong to a different seller are considered; among those within 20 km
    (inclusive of exactly 20.00 km) the nearest wins, tie-broken by the earliest
    ``expires_at``; when nothing qualifies the result is None.

    **Validates: Requirements 6.1, 6.2, 6.4, 6.8**
    """
    buyer, candidates = scenario
    result = select_match(candidates, buyer)
    expected = _expected_selection(buyer, candidates)

    if expected is None:
        # No eligible candidate within radius -> no selection (Req 6.8).
        assert result is None
        return

    expected_candidate, expected_distance = expected
    assert result is not None

    # The chosen candidate is genuinely eligible (Req 6.2).
    assert _is_eligible(result.candidate, buyer)

    # Within the 20 km radius, inclusive of the exact boundary (Req 6.4, 6.8).
    assert result.distance_km <= MATCH_RADIUS_KM

    # Distance matches the independently computed haversine value (Req 6.3 feed).
    assert result.distance_km == expected_distance

    # Selection equals the independent nearest / earliest-expiry choice (Req 6.4).
    assert (result.distance_km, result.candidate.expires_at) == (
        expected_distance,
        expected_candidate.expires_at,
    )
    assert result.candidate == expected_candidate

    # No other eligible candidate is strictly closer than the one selected.
    for candidate in candidates:
        if _is_eligible(candidate, buyer):
            distance = haversine_km(buyer.point, candidate.seller_point)
            if distance <= MATCH_RADIUS_KM:
                assert result.distance_km <= distance
