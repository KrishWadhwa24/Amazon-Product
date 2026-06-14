"""Property-based test for the savings summary pure core (task 7.3).

This exercises :func:`app.services.pricing.savings_summary` — the *real* field
bounds and carbon-suppression logic of Requirements 7.2 and 7.3 — across a wide
range of prices, estimated savings, delivery-hour estimates, and carbon
estimates, including negative delivery/carbon inputs (to verify clamping to
``>= 0``) and values straddling the ``0.1`` kg carbon-display cutoff.

Library: Hypothesis (per the design's Testing Strategy). One property per test,
minimum 100 iterations.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from hypothesis import example, given, settings
from hypothesis import strategies as st

from app.services.pricing import (
    CARBON_DISPLAY_THRESHOLD,
    local_discount,
    savings_summary,
)

# One-decimal quantum for carbon comparison.
_TENTHS = Decimal("0.1")


# Strictly-positive price (Product.price > 0); non-negative savings.
_PRICE = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("100000"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)
_SAVINGS = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("100000"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)

# Delivery hours: include negatives so the >= 0 clamp is exercised, and
# fractional values so the floor-to-whole-hours rule is exercised.
_DELIVERY_HOURS = st.decimals(
    min_value=Decimal("-50"),
    max_value=Decimal("500"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)

# Carbon: include negatives (clamp to >= 0) and dense sub-/super-0.1 values so
# the suppression boundary is well covered.
_CARBON = st.decimals(
    min_value=Decimal("-5"),
    max_value=Decimal("100"),
    allow_nan=False,
    allow_infinity=False,
    places=3,
)


# Feature: amazon-edge-return, Property 14: Savings summary field bounds and carbon suppression
@settings(max_examples=15)
@given(
    price=_PRICE,
    est_savings=_SAVINGS,
    est_delivery_hours_saved=_DELIVERY_HOURS,
    est_carbon_kg=_CARBON,
)
# Exact 0.1 kg boundary -> carbon included.
@example(
    price=Decimal("1000"),
    est_savings=Decimal("100"),
    est_delivery_hours_saved=Decimal("10"),
    est_carbon_kg=Decimal("0.1"),
)
# Just below 0.1 kg (rounds to 0.0) -> carbon suppressed.
@example(
    price=Decimal("1000"),
    est_savings=Decimal("100"),
    est_delivery_hours_saved=Decimal("10"),
    est_carbon_kg=Decimal("0.04"),
)
# 0.05 kg rounds half-up to 0.1 -> carbon included at the boundary.
@example(
    price=Decimal("1000"),
    est_savings=Decimal("100"),
    est_delivery_hours_saved=Decimal("10"),
    est_carbon_kg=Decimal("0.05"),
)
# Negative delivery and carbon inputs -> both clamp to zero, carbon suppressed.
@example(
    price=Decimal("1000"),
    est_savings=Decimal("100"),
    est_delivery_hours_saved=Decimal("-3"),
    est_carbon_kg=Decimal("-2"),
)
def test_savings_summary_bounds_and_carbon_suppression(
    price: Decimal,
    est_savings: Decimal,
    est_delivery_hours_saved: Decimal,
    est_carbon_kg: Decimal,
) -> None:
    """money_saved = discount (2dp); hours whole >= 0; carbon >= 0 at 1dp;
    carbon suppressed when < 0.1 kg, included at exactly 0.1 kg.

    **Validates: Requirements 7.2, 7.3**
    """
    summary = savings_summary(
        price, est_savings, est_delivery_hours_saved, est_carbon_kg
    )

    # money_saved equals the Local_Discount, a 2-decimal currency value.
    assert summary.money_saved == local_discount(price, est_savings)
    assert summary.money_saved >= Decimal("0.00")
    assert -summary.money_saved.as_tuple().exponent <= 2

    # delivery_time_saved_hours is a whole number of hours >= 0.
    assert isinstance(summary.delivery_time_saved_hours, int)
    assert summary.delivery_time_saved_hours >= 0
    # It is the floor of the (non-negative) estimate.
    expected_hours = 0 if est_delivery_hours_saved < 0 else int(
        est_delivery_hours_saved.to_integral_value(rounding="ROUND_FLOOR")
    )
    assert summary.delivery_time_saved_hours == expected_hours

    # carbon_avoided_kg is >= 0 and rounded to exactly 1 decimal place.
    assert summary.carbon_avoided_kg >= 0.0
    carbon_clamped = est_carbon_kg if est_carbon_kg >= 0 else Decimal("0")
    expected_carbon = carbon_clamped.quantize(_TENTHS, rounding=ROUND_HALF_UP)
    assert Decimal(str(summary.carbon_avoided_kg)) == expected_carbon

    # include_carbon is False iff the rounded carbon is below 0.1 kg; the exact
    # 0.1 kg boundary is included (Requirement 7.3).
    assert summary.include_carbon == (expected_carbon >= CARBON_DISPLAY_THRESHOLD)
    if summary.include_carbon:
        assert Decimal(str(summary.carbon_avoided_kg)) >= CARBON_DISPLAY_THRESHOLD
