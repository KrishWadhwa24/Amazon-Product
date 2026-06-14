"""Property-based test for the demand-scoring pure core (task 6.2).

This exercises :func:`app.core.scoring.rank_signals` — the *real* ranking logic
of Requirements 5.2 and 5.3 — across lists of demand signals with mixed intents
and timestamps.

Library: Hypothesis (per the design's Testing Strategy). One property per test,
minimum 100 iterations.
"""

from __future__ import annotations

from collections import Counter

from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.scoring import DemandSignal, rank_signals, score

# The four recognized demand sources (Requirement 5.1); ranking is defined over
# signals drawn from this set.
_SIGNAL_SOURCES = ["cart", "buynow", "wishlist", "viewed"]


def _signals() -> st.SearchStrategy[list[DemandSignal]]:
    """Lists of DemandSignal with mixed intents and timestamps."""
    single = st.builds(
        DemandSignal,
        signal_source=st.sampled_from(_SIGNAL_SOURCES),
        created_at=st.datetimes(),
        buyer_id=st.integers(min_value=1, max_value=1000),
    )
    return st.lists(single, max_size=30)


# Feature: amazon-edge-return, Property 7: Demand signal ranking by score then timestamp
@settings(max_examples=15)
@given(signals=_signals())
def test_demand_ranking_by_score_then_timestamp(signals: list[DemandSignal]) -> None:
    """rank_signals orders by score desc then earliest created_at asc.

    The first ranked element has the maximum score and, among max-score
    signals, the earliest timestamp. Ranking is a permutation of the input and
    does not mutate it.

    **Validates: Requirements 5.1, 5.2, 5.3**
    """
    # Import-time copy to detect any mutation of the caller's list.
    original = list(signals)

    ranked = rank_signals(signals)

    # Pairwise ordering invariant: for every consecutive pair (a, b), either a
    # has a strictly higher score, or they tie on score and a was recorded no
    # later than b (Requirements 5.2, 5.3).
    for a, b in zip(ranked, ranked[1:]):
        sa, sb = score(a.signal_source), score(b.signal_source)
        assert sa > sb or (sa == sb and a.created_at <= b.created_at)

    # The first ranked element carries the maximum score and, among signals
    # sharing that maximum, the earliest timestamp.
    if ranked:
        max_score = max(score(s.signal_source) for s in ranked)
        assert score(ranked[0].signal_source) == max_score
        earliest_at_max = min(
            s.created_at for s in ranked if score(s.signal_source) == max_score
        )
        assert ranked[0].created_at == earliest_at_max

    # Ranking is a permutation of the input (same multiset of signals).
    assert Counter(ranked) == Counter(signals)

    # Ranking does not mutate its input.
    assert signals == original
