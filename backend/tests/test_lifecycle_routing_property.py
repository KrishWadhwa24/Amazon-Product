"""Property-based test for expiry auto-routing (task 5.4).

Feature: amazon-edge-return, Property 20: Expiry auto-routing is total and threshold-driven

This exercises the pure routing core
:func:`app.services.lifecycle.decide_expiry_route` together with
:func:`app.services.lifecycle.compute_reverse_transit_threshold` over arbitrary
non-negative money values (using :class:`~decimal.Decimal` so the comparison is
exact). It asserts the single design property: for any product price and
estimated reverse-logistics cost, the threshold is ``cost + ₹150`` and the route
is *exactly* NGO_ROUTING when ``price <= threshold`` and *exactly* MICROWAREHOUSE
when ``price > threshold`` — i.e. routing is total (always exactly one of the two
terminal-ward states) and threshold-driven. ``@example`` cases pin prices that
straddle the threshold (just below, equal, just above).

Validates: Requirements 10.9, 10.10, 10.11, 10.12
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import example, given, settings
from hypothesis import strategies as st

from app.models.enums import ReturnStatus
from app.services.lifecycle import (
    REVERSE_TRANSIT_BUFFER,
    compute_reverse_transit_threshold,
    decide_expiry_route,
)

# Non-negative money values as Decimals with up to two fractional places, bounded
# to a plausible currency range so generation stays in the intended input space.
_money = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("1000000"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)


@settings(max_examples=15)
@given(price=_money, cost=_money)
# Prices straddling the threshold (cost=100 -> threshold=250): just below, equal,
# just above. These are the deterministic boundary cases the property must pin.
@example(price=Decimal("249.99"), cost=Decimal("100"))  # just below -> NGO_ROUTING
@example(price=Decimal("250"), cost=Decimal("100"))  # equal -> NGO_ROUTING
@example(price=Decimal("250.01"), cost=Decimal("100"))  # just above -> MICROWAREHOUSE
def test_expiry_auto_routing_is_total_and_threshold_driven(
    price: Decimal, cost: Decimal
) -> None:
    """threshold == cost + 150; route is exactly NGO_ROUTING iff price <= threshold."""
    threshold = compute_reverse_transit_threshold(cost)

    # The threshold is the cost plus the fixed ₹150 buffer (Requirement 10.9).
    assert threshold == cost + REVERSE_TRANSIT_BUFFER

    route = decide_expiry_route(price, cost)

    # Routing is total and threshold-driven: exactly one of the two states, chosen
    # by the price-vs-threshold comparison (Requirements 10.10, 10.11, 10.12).
    if price <= threshold:
        assert route is ReturnStatus.NGO_ROUTING
    else:
        assert route is ReturnStatus.MICROWAREHOUSE

    # Totality restated: the route is always exactly one of the two terminal-ward
    # states and never anything else.
    assert route in (ReturnStatus.NGO_ROUTING, ReturnStatus.MICROWAREHOUSE)
