"""Local deal price optimization and savings impact (Requirement 7).

This module is a **pure, side-effect-free decision core**. It performs the
*real* clamp/rounding math that turns a product price and an estimated
logistics savings into a buyer-facing local-deal discount and savings summary,
and it decides whether an environmental claim is substantial enough to show.

It deliberately imports nothing from FastAPI, SQLAlchemy, or Redis so it can be
exercised in isolation by the property tests (Properties 13 and 14).

Real vs mocked (per the prototype's mock-vs-real directive)
-----------------------------------------------------------
- **Real:** :func:`local_discount` (the ``MIN(savings, 15% * price)`` clamp,
  2-decimal currency rounding, and the "< 0.01 -> 0.00" rule, Requirement 7.1)
  and the field bounds / carbon suppression in :func:`savings_summary`
  (Requirements 7.2, 7.3).
- **Mocked:** the *inputs* — the estimated logistics savings, the delivery
  hours saved, and the carbon avoided — are produced by
  :func:`estimate_logistics`, a clearly-marked deterministic stand-in. It lives
  behind a stable seam so a real estimation engine can replace it later without
  touching the pure clamp/summary logic above.

Currency is handled with :class:`~decimal.Decimal` for correctness; rounding
uses banker-free ``ROUND_HALF_UP`` so a value like ``0.005`` rounds up to
``0.01`` the way buyers expect money to round.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Union

# Accepted numeric input types for prices/savings. ``float`` is converted via
# ``str`` so we never inherit binary-float artifacts (e.g. 0.1 + 0.2) into the
# currency math.
Number = Union[int, float, Decimal, str]

# --- Constants drawn directly from Requirement 7 ---------------------------

#: Local_Discount is capped at 15% of the product price (Requirement 7.1).
LOCAL_DISCOUNT_RATE: Decimal = Decimal("0.15")

#: Two-decimal currency quantum and the zero currency value.
_CENTS: Decimal = Decimal("0.01")
ZERO_MONEY: Decimal = Decimal("0.00")

#: A computed discount below this floor is reported as 0.00 (Requirement 7.1).
MIN_DISCOUNT: Decimal = Decimal("0.01")

#: One-decimal kilogram quantum for carbon display.
_TENTHS: Decimal = Decimal("0.1")

#: Carbon avoided below this is suppressed from the notification (Requirement 7.3).
CARBON_DISPLAY_THRESHOLD: Decimal = Decimal("0.1")


def _to_decimal(value: Number) -> Decimal:
    """Coerce a numeric input to :class:`Decimal` without float artifacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):  # guard: bool is an int subclass
        raise TypeError("numeric value expected, got bool")
    # ``str()`` first so floats like 0.1 become exactly Decimal("0.1").
    return Decimal(str(value))


def _round_money(value: Decimal) -> Decimal:
    """Round a Decimal to a 2-decimal currency value, half-up."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def local_discount(price: Number, est_savings: Number) -> Decimal:
    """Return the Local_Discount for a product (Requirement 7.1).

    ``Local_Discount = clamp_nonneg(MIN(est_savings, 0.15 * price))`` rounded to
    two decimal places, with any rounded value strictly below ``0.01`` reported
    as ``0.00``.

    The result is always a non-negative :class:`Decimal` with exactly two
    decimal places, never exceeds the estimated savings, and never exceeds 15%
    of the price.
    """
    price_d = _to_decimal(price)
    savings_d = _to_decimal(est_savings)

    # MIN(estimated logistics savings, 15% of product price).
    cap = LOCAL_DISCOUNT_RATE * price_d
    raw = savings_d if savings_d < cap else cap

    # Clamp to non-negative, then round to currency precision.
    if raw < ZERO_MONEY:
        raw = ZERO_MONEY
    rounded = _round_money(raw)

    # Sub-cent discounts are treated as no discount.
    if rounded < MIN_DISCOUNT:
        return ZERO_MONEY
    return rounded


@dataclass(frozen=True)
class SavingsSummary:
    """Buyer-facing savings impact for a local open-box deal (Requirement 7.2).

    Attributes:
        money_saved: The Local_Discount as a 2-decimal currency value.
        delivery_time_saved_hours: Whole hours saved, ``>= 0``.
        carbon_avoided_kg: CO2 avoided in kg, rounded to 1 decimal, ``>= 0``.
        include_carbon: ``False`` when ``carbon_avoided_kg < 0.1`` so the
            notification omits the carbon field and makes no environmental
            claim (Requirement 7.3); ``True`` otherwise.
    """

    money_saved: Decimal
    delivery_time_saved_hours: int
    carbon_avoided_kg: float
    include_carbon: bool


def savings_summary(
    price: Number,
    est_savings: Number,
    est_delivery_hours_saved: Number,
    est_carbon_kg: Number,
) -> SavingsSummary:
    """Build the savings summary for a match notification (Requirements 7.2, 7.3).

    The estimation *inputs* (``est_savings``, ``est_delivery_hours_saved``,
    ``est_carbon_kg``) are mocked deterministic values produced by
    :func:`estimate_logistics`; the bounds and rounding applied here are real.

    - ``money_saved`` equals :func:`local_discount` (currency, 2 dp).
    - ``delivery_time_saved_hours`` is a whole number of hours ``>= 0``
      (negative or fractional estimates floor toward zero).
    - ``carbon_avoided_kg`` is ``>= 0`` rounded to 1 decimal place.
    - ``include_carbon`` is ``False`` when carbon ``< 0.1`` kg, so the
      notification omits any environmental claim (Requirement 7.3). The exact
      ``0.1`` kg boundary is included (claim shown).
    """
    money_saved = local_discount(price, est_savings)

    # Whole hours, never negative (Requirement 7.2).
    hours_d = _to_decimal(est_delivery_hours_saved)
    if hours_d < 0:
        delivery_hours = 0
    else:
        delivery_hours = int(math.floor(hours_d))

    # Carbon avoided: clamp non-negative, round to 1 dp using Decimal so the
    # 0.1 kg suppression boundary is exact (Requirements 7.2, 7.3).
    carbon_d = _to_decimal(est_carbon_kg)
    if carbon_d < 0:
        carbon_d = Decimal("0")
    carbon_rounded = carbon_d.quantize(_TENTHS, rounding=ROUND_HALF_UP)
    include_carbon = carbon_rounded >= CARBON_DISPLAY_THRESHOLD

    return SavingsSummary(
        money_saved=money_saved,
        delivery_time_saved_hours=delivery_hours,
        carbon_avoided_kg=float(carbon_rounded),
        include_carbon=include_carbon,
    )


# --- Mocked estimation seam -------------------------------------------------
# NOTE: MOCK / HARDCODED. The values below are deterministic plausible
# stand-ins, NOT a real reverse-logistics model. They exist so the buyer-facing
# notification is end-to-end demonstrable. Swap this single function for a real
# estimator later; the pure clamp/summary logic above does not change.

#: Mock: reverse logistics savings scale at ~12% of the product price.
_MOCK_SAVINGS_RATE: Decimal = Decimal("0.12")

#: Mock: a returned-to-FC delivery takes ~46h; a local open-box deal ~2h.
_MOCK_FC_DELIVERY_HOURS: int = 46
_MOCK_LOCAL_DELIVERY_HOURS: int = 2

#: Mock: CO2 avoided ~ 0.05 kg per km of reverse transit not driven.
_MOCK_CARBON_PER_KM: Decimal = Decimal("0.05")


def estimate_logistics(
    product_price: Number, distance_km: Number
) -> tuple[Decimal, int, Decimal]:
    """MOCK deterministic logistics estimate (swappable seam).

    Returns ``(est_savings, delivery_hours_saved, carbon_kg)`` for a candidate
    local deal:

    - ``est_savings`` scales with the product price (mock ~12%).
    - ``delivery_hours_saved`` is the fixed FC-vs-local delivery gap (~44h).
    - ``carbon_kg`` scales with the local distance not driven through reverse
      transit (mock ~0.05 kg/km).

    These are plausible hardcoded values for the prototype only. The pure
    consumers (:func:`local_discount`, :func:`savings_summary`) clamp and round
    whatever this seam returns, so a real estimator can replace it freely.
    """
    price_d = _to_decimal(product_price)
    distance_d = _to_decimal(distance_km)
    if distance_d < 0:
        distance_d = Decimal("0")

    est_savings = _round_money(_MOCK_SAVINGS_RATE * price_d)
    delivery_hours_saved = max(0, _MOCK_FC_DELIVERY_HOURS - _MOCK_LOCAL_DELIVERY_HOURS)
    carbon_kg = (_MOCK_CARBON_PER_KM * distance_d).quantize(
        _TENTHS, rounding=ROUND_HALF_UP
    )
    return est_savings, delivery_hours_saved, carbon_kg
