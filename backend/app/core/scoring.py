"""Demand-signal scoring and ranking (Requirement 5).

This is a **pure**, side-effect-free decision core: it performs no database or
network I/O so it can be property-tested independently of the matching engine's
I/O shell (see the "Demand Scoring & Selection" section of the design document).

The Matching_Engine assigns a Demand_Score to each demand signal source and,
when several signals compete for a single ReturnOrder, ranks them so the
strongest purchase intent is offered the deal first:

* ``cart``     -> 100  (Requirement 5.1)
* ``buynow``   ->  90  (Requirement 5.1)
* ``wishlist`` ->  70  (Requirement 5.1)
* ``viewed``   ->  40  (Requirement 5.1)

Ranking is by Demand_Score descending; ties are broken by the earliest recorded
timestamp ascending (Requirements 5.2, 5.3).

Signal-source naming is kept consistent with the rest of the system
(``MatchCandidate.signal_source`` and the Redis ``demand:{intent}:{asin}`` keys):
``cart``, ``buynow``, ``wishlist``, ``viewed``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Protocol, TypeVar, runtime_checkable

__all__ = [
    "DEMAND_SCORES",
    "DemandSignal",
    "SignalLike",
    "score",
    "rank_signals",
]


# Canonical Demand_Score weights keyed by signal source (Requirement 5.1).
DEMAND_SCORES: dict[str, int] = {
    "cart": 100,
    "buynow": 90,
    "wishlist": 70,
    "viewed": 40,
}


@runtime_checkable
class SignalLike(Protocol):
    """Structural type accepted by :func:`rank_signals`.

    Any object exposing a signal-source attribute (``signal_source`` or
    ``type``) and a recorded-timestamp attribute (``created_at`` or
    ``timestamp``) can be ranked. The concrete :class:`DemandSignal` dataclass
    below satisfies this protocol.
    """

    signal_source: str
    created_at: datetime


@dataclass(frozen=True)
class DemandSignal:
    """A buyer intent event considered for matching.

    Attributes:
        signal_source: One of ``cart``, ``buynow``, ``wishlist``, ``viewed``.
        created_at: The timestamp the signal was recorded (tie-break key).
        buyer_id: Optional identifier of the buyer that produced the signal.
    """

    signal_source: str
    created_at: datetime
    buyer_id: int | None = None


T = TypeVar("T")


def _signal_source(signal: object) -> str:
    """Read the signal source from either ``signal_source`` or ``type``."""
    if hasattr(signal, "signal_source"):
        return getattr(signal, "signal_source")
    if hasattr(signal, "type"):
        return getattr(signal, "type")
    raise AttributeError(
        "signal must expose a 'signal_source' or 'type' attribute"
    )


def _timestamp(signal: object) -> datetime:
    """Read the recorded timestamp from either ``created_at`` or ``timestamp``."""
    if hasattr(signal, "created_at"):
        return getattr(signal, "created_at")
    if hasattr(signal, "timestamp"):
        return getattr(signal, "timestamp")
    raise AttributeError(
        "signal must expose a 'created_at' or 'timestamp' attribute"
    )


def score(signal_type: str) -> int:
    """Return the Demand_Score for a signal source (Requirement 5.1).

    Args:
        signal_type: One of ``cart``, ``buynow``, ``wishlist``, ``viewed``.

    Returns:
        Exactly ``100`` for ``cart``, ``90`` for ``buynow``, ``70`` for
        ``wishlist``, and ``40`` for ``viewed``.

    Raises:
        KeyError: If ``signal_type`` is not a recognized demand source.
    """
    return DEMAND_SCORES[signal_type]


def rank_signals(signals: Iterable[T]) -> list[T]:
    """Rank demand signals strongest-intent-first (Requirements 5.2, 5.3).

    Signals are ordered by Demand_Score descending; ties are broken by the
    earliest recorded timestamp ascending. The first element therefore has the
    maximum score and, among signals sharing that maximum score, the earliest
    timestamp.

    This function is pure: it returns a new list and never mutates its input.

    Args:
        signals: An iterable of signal-like objects, each exposing a signal
            source (``signal_source`` or ``type``) and a timestamp
            (``created_at`` or ``timestamp``).

    Returns:
        A new list of the same signals in ranked order.
    """
    materialized = list(signals)
    # Sort is stable; the (-score, timestamp) key yields score-desc then
    # earliest-timestamp-first without mutating the input list.
    return sorted(
        materialized,
        key=lambda s: (-score(_signal_source(s)), _timestamp(s)),
    )
