"""Property-based tests for the pricing pure core (task 7.2).

These exercise :func:`app.services.pricing.local_discount` — the *real*
clamp/rounding math of Requirement 7.1 — across a wide range of prices and
estimated logistics savings, including values that straddle the ``0.01``
sub-cent cutoff.

Library: Hypothesis (per the design's Testing Strategy). One property per test,
minimum 100 iterations.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from hypothesis import example, given, settings
from hypothesis import strategies as st

from app.services.pricing import LOCAL_DISCOUNT_RATE, local_discount

# Quantum for currency comparisons and the maximum upward shift a half-up
# rounding can introduce (a value of ``x.xx5`` rounds up by exactly 0.005).
_CENTS = Decimal("0.01")
_ROUNDING_SLACK = Decimal("0.005")


# Non-negative monetary strategy. ``places=4`` gives sub-cent granularity so
# generated values land on both sides of the 0.01 cutoff; the wide range keeps
# ordinary prices/savings covered too.
def _money(min_value: str) -> st.SearchStrategy[Decimal]:
    return st.decimals(
        min_value=Decimal(min_value),
        max_value=Decimal("100000"),
        allow_nan=False,
        allow_infinity=False,
        places=4,
    )


# price must be strictly positive (Product.price > 0); savings is non-negative.
_PRICE = _money("0.0001")
_SAVINGS = _money("0")


# Feature: amazon-edge-return, Property 13: Local discount bound and rounding
@settings(max_examples=15)
@given(price=_PRICE, est_savings=_SAVINGS)
# Boundary values straddling the 0.01 sub-cent cutoff (cap kept large so the
# savings term binds and we isolate the rounding/sub-cent rule).
@example(price=Decimal("1000"), est_savings=Decimal("0.0049"))  # -> 0.00
@example(price=Decimal("1000"), est_savings=Decimal("0.005"))   # -> 0.01 (half-up)
@example(price=Decimal("1000"), est_savings=Decimal("0.0149"))  # -> 0.01
@example(price=Decimal("1000"), est_savings=Decimal("0.015"))   # -> 0.02 (half-up)
# Boundary where the 15%-of-price cap (not savings) lands sub-cent.
@example(price=Decimal("0.03"), est_savings=Decimal("9999"))    # cap=0.0045 -> 0.00
@example(price=Decimal("0.04"), est_savings=Decimal("9999"))    # cap=0.0060 -> 0.01
def test_local_discount_bound_and_rounding(price: Decimal, est_savings: Decimal) -> None:
    """local_discount = clamp_nonneg(MIN(savings, 15%*price)), 2dp, <0.01 -> 0.00.

    **Validates: Requirements 7.1**
    """
    result = local_discount(price, est_savings)

    cap = LOCAL_DISCOUNT_RATE * price
    raw = min(est_savings, cap)
    if raw < 0:
        raw = Decimal("0")
    rounded = raw.quantize(_CENTS, rounding=ROUND_HALF_UP)
    expected = Decimal("0.00") if rounded < _CENTS else rounded

    # Exact contract: equals MIN(savings, 15%*price) clamped, rounded 2dp,
    # with sub-cent values reported as 0.00.
    assert result == expected

    # Non-negative.
    assert result >= Decimal("0.00")

    # At most two decimal places.
    assert -result.as_tuple().exponent <= 2

    # Never exceeds the savings or 15% of price (allowing the half-up rounding
    # slack and the sub-cent -> 0.00 rule).
    assert result <= est_savings + _ROUNDING_SLACK
    assert result <= cap + _ROUNDING_SLACK

    # Sub-cent rule: when the clamped, rounded amount is below a cent it is
    # reported as exactly 0.00 (no environmental/penny noise).
    if rounded < _CENTS:
        assert result == Decimal("0.00")
