"""Return lifecycle state machine — pure decision core (Requirement 10).

This module encodes the **exact** ReturnOrder transition relation from the
design's "Return Lifecycle State Machine" section as a single immutable table
and exposes pure, side-effect-free helpers over it:

* :data:`TRANSITIONS`        — the source -> allowed-targets relation.
* :func:`allowed_targets`    — the set of legal next states for a status.
* :func:`is_terminal`        — whether a status has no outgoing transition.
* :func:`is_valid_transition`— whether a (source, target) pair is permitted.
* :func:`transition`         — returns the new status for a legal pair, else
  raises :class:`~app.core.errors.InvalidTransitionError`.

The table (design transition table; Requirements 10.1–10.8):

    SCANNING       -> {MATCH_FOUND, EXPIRED, NGO_ROUTING, MICROWAREHOUSE}
    MATCH_FOUND    -> {BUYER_ACCEPTED}
    BUYER_ACCEPTED -> {LOCAL_DELIVERY}
    EXPIRED        -> {FC_TRANSIT, NGO_ROUTING, MICROWAREHOUSE}
    LOCAL_DELIVERY -> {}   (terminal)
    FC_TRANSIT     -> {}   (terminal)
    NGO_ROUTING    -> {}   (terminal)
    MICROWAREHOUSE -> {}   (terminal)

The functions perform **no I/O and no mutation**: a rejected transition raises
without changing anything, so the same core can drive the API endpoint
(task 8.4) and be property-tested (task 5.3).
"""

from __future__ import annotations

from decimal import Decimal
from types import MappingProxyType
from typing import Mapping

from app.core.errors import InvalidTransitionError
from app.models.enums import ReturnStatus

# Fixed reverse-transit buffer added to the estimated reverse-logistics cost
# when deciding expiry routing (Requirement 10.9): ₹150.
REVERSE_TRANSIT_BUFFER: Decimal = Decimal("150")

# The exact transition relation. Every status is a key (states with no outgoing
# transition map to an empty frozenset) so the relation is total over the enum
# and terminal states are explicit rather than implied by omission.
TRANSITIONS: Mapping[ReturnStatus, frozenset[ReturnStatus]] = MappingProxyType(
    {
        ReturnStatus.SCANNING: frozenset(
            {
                ReturnStatus.MATCH_FOUND,
                ReturnStatus.EXPIRED,
                ReturnStatus.NGO_ROUTING,
                ReturnStatus.MICROWAREHOUSE,
            }
        ),
        ReturnStatus.MATCH_FOUND: frozenset({ReturnStatus.BUYER_ACCEPTED}),
        ReturnStatus.BUYER_ACCEPTED: frozenset({ReturnStatus.LOCAL_DELIVERY}),
        ReturnStatus.EXPIRED: frozenset(
            {
                ReturnStatus.FC_TRANSIT,
                ReturnStatus.NGO_ROUTING,
                ReturnStatus.MICROWAREHOUSE,
            }
        ),
        # Terminal states (Requirement 10.6): no outgoing transition.
        ReturnStatus.LOCAL_DELIVERY: frozenset(),
        ReturnStatus.FC_TRANSIT: frozenset(),
        ReturnStatus.NGO_ROUTING: frozenset(),
        ReturnStatus.MICROWAREHOUSE: frozenset(),
    }
)

# Terminal states, derived from the table so the two never drift apart.
TERMINAL_STATES: frozenset[ReturnStatus] = frozenset(
    status for status, targets in TRANSITIONS.items() if not targets
)


def allowed_targets(status: ReturnStatus) -> frozenset[ReturnStatus]:
    """Return the set of legal next states for ``status``.

    Terminal states return an empty frozenset (Requirement 10.6).
    """
    return TRANSITIONS[status]


def is_terminal(status: ReturnStatus) -> bool:
    """Return ``True`` when ``status`` has no outgoing transition.

    Terminal states are LOCAL_DELIVERY, FC_TRANSIT, NGO_ROUTING, and
    MICROWAREHOUSE (Requirement 10.6).
    """
    return not TRANSITIONS[status]


def is_valid_transition(source: ReturnStatus, target: ReturnStatus) -> bool:
    """Return ``True`` iff ``(source, target)`` is in the lifecycle relation."""
    return target in TRANSITIONS[source]


def transition(source: ReturnStatus, target: ReturnStatus) -> ReturnStatus:
    """Return ``target`` when the ``source -> target`` transition is defined.

    For a transition present in :data:`TRANSITIONS` this returns ``target``
    (the resulting status; Requirements 10.1–10.5, 10.8). For any undefined
    pair — including any transition out of a terminal state — it raises
    :class:`~app.core.errors.InvalidTransitionError` naming both the source and
    target and mutates nothing, since the function is pure (Requirements 10.6,
    10.7).
    """
    if target in TRANSITIONS[source]:
        return target
    raise InvalidTransitionError(source, target)


def compute_reverse_transit_threshold(
    estimated_reverse_logistics_cost: Decimal | int | str,
) -> Decimal:
    """Return the Reverse_Transit_Threshold for an expiring ReturnOrder.

    The threshold is ``Estimated_Reverse_Logistics_Cost + ₹150`` (Requirement
    10.9). The ``estimated_reverse_logistics_cost`` is sourced from the seeded
    ``Product.estimated_reverse_logistics_cost`` column — in the prototype a
    mocked/hardcoded plausible value — but the computation here is **real** and
    pure: same input always yields the same threshold, with no I/O or mutation.

    The input is coerced to :class:`~decimal.Decimal` so the money arithmetic is
    exact and matches the comparison performed in :func:`decide_expiry_route`.
    """
    cost = (
        estimated_reverse_logistics_cost
        if isinstance(estimated_reverse_logistics_cost, Decimal)
        else Decimal(str(estimated_reverse_logistics_cost))
    )
    return cost + REVERSE_TRANSIT_BUFFER


def decide_expiry_route(
    product_price: Decimal | int | str,
    estimated_reverse_logistics_cost: Decimal | int | str,
) -> ReturnStatus:
    """Decide the automatic post-EXPIRED route for a ReturnOrder.

    On the ``SCANNING -> EXPIRED`` transition the system computes
    ``Reverse_Transit_Threshold = estimated_reverse_logistics_cost + ₹150``
    (Requirement 10.9) and auto-routes to exactly one terminal-ward state
    (Requirement 10.12):

    * ``product_price <= threshold`` -> :attr:`ReturnStatus.NGO_ROUTING`
      (Requirement 10.10)
    * ``product_price >  threshold`` -> :attr:`ReturnStatus.MICROWAREHOUSE`
      (Requirement 10.11)

    The threshold and comparison are **real** and use :class:`~decimal.Decimal`
    for exact money arithmetic so prices straddling the threshold route
    deterministically. ``estimated_reverse_logistics_cost`` is sourced from the
    seeded ``Product`` column (a mocked/hardcoded plausible value); keeping it a
    parameter rather than reading the product here leaves the seam swappable and
    the function pure for property testing (task 5.4).
    """
    price = (
        product_price
        if isinstance(product_price, Decimal)
        else Decimal(str(product_price))
    )
    threshold = compute_reverse_transit_threshold(estimated_reverse_logistics_cost)
    if price <= threshold:
        return ReturnStatus.NGO_ROUTING
    return ReturnStatus.MICROWAREHOUSE
