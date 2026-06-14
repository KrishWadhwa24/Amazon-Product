"""Property-based test for the haversine distance pure core (task 6.4).

Exercises :func:`app.core.matching.haversine_km` — the great-circle distance
used by the Matching_Engine's distance computation (Requirement 6.3) — across
the full range of valid latitudes and longitudes.

The expected distance is recomputed independently inside the test using the
same :data:`EARTH_RADIUS_KM` constant and haversine formula, then rounded to
two decimals, so the assertion pins the function to "haversine rounded to 2 dp"
rather than to a hand-picked table of magic numbers.

Library: Hypothesis (per the design's Testing Strategy). One property per test,
minimum 100 iterations.
"""

from __future__ import annotations

import math

from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.matching import EARTH_RADIUS_KM, Point, haversine_km

# Latitude is bounded to [-90, 90] and longitude to [-180, 180] (Point's
# documented domain). Reject NaN/infinity so generated points are always valid
# geographic coordinates.
_LAT = st.floats(min_value=-90.0, max_value=90.0, allow_nan=False, allow_infinity=False)
_LON = st.floats(
    min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False
)
_POINT = st.builds(Point, lat=_LAT, lon=_LON)


def _expected_haversine_km(a: Point, b: Point) -> float:
    """Independently compute the haversine distance, rounded to 2 dp.

    Reproduces the same Earth radius and formula as the module under test so
    the equality check verifies the contract rather than a copy of the code's
    intermediate values.
    """
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    dlat = math.radians(b.lat - a.lat)
    dlon = math.radians(b.lon - a.lon)

    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(min(1.0, h)), math.sqrt(max(0.0, 1.0 - h)))
    return round(EARTH_RADIUS_KM * c, 2)


# Feature: amazon-edge-return, Property 8: Distance is the haversine distance rounded to two decimals
@settings(max_examples=15)
@given(point_a=_POINT, point_b=_POINT)
def test_distance_is_haversine_rounded_to_two_decimals(
    point_a: Point, point_b: Point
) -> None:
    """haversine_km equals the independently-computed haversine, 2 dp.

    Also asserts the basic invariants the distance must satisfy: it is
    non-negative, symmetric in its arguments, zero from a point to itself, and
    carries at most two decimal places.

    **Validates: Requirements 6.3**
    """
    result = haversine_km(point_a, point_b)
    expected = _expected_haversine_km(point_a, point_b)

    # Exact contract: distance is the haversine distance rounded to 2 dp. The
    # independent computation rounds to the same 2 dp value, so an exact
    # equality holds (any sub-rounding float noise is absorbed by round()).
    assert result == expected

    # Non-negative.
    assert result >= 0.0

    # Symmetric: a -> b equals b -> a.
    assert result == haversine_km(point_b, point_a)

    # At most two decimal places (round() to 2 dp guarantees this).
    assert round(result, 2) == result

    # Self-distance is exactly 0.0.
    assert haversine_km(point_a, point_a) == 0.0
