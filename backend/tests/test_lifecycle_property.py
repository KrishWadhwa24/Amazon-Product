"""Property-based test for the return lifecycle state machine (task 5.3).

Feature: amazon-edge-return, Property 19: State-machine legality matches the transition table

This exercises the pure :func:`app.services.lifecycle.transition` core across the
full ReturnStatus cross-product so undefined and terminal-source transitions are
covered. It asserts the single design property: a transition is permitted iff the
(source, target) pair is in ``TRANSITIONS``; a permitted transition returns exactly
the target; any unpermitted pair (including any transition from a terminal state)
raises :class:`InvalidTransitionError` naming the source and target.

Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.errors import InvalidTransitionError
from app.models.enums import ReturnStatus
from app.services.lifecycle import TRANSITIONS, transition

# Sample both endpoints of the transition from the full enum so the property
# explores the entire ReturnStatus x ReturnStatus cross-product, including
# undefined pairs and transitions out of terminal states.
_status = st.sampled_from(list(ReturnStatus))


@settings(max_examples=15)
@given(source=_status, target=_status)
def test_state_machine_legality_matches_transition_table(
    source: ReturnStatus, target: ReturnStatus
) -> None:
    """Permitted iff in the table; permitted returns target, else raises naming both."""
    permitted = target in TRANSITIONS[source]

    if permitted:
        # A permitted transition sets the status to exactly the target.
        result = transition(source, target)
        assert result is target
    else:
        # Any unpermitted pair (including terminal-source) is rejected with an
        # invalid-transition error identifying both the source and the target.
        try:
            transition(source, target)
        except InvalidTransitionError as exc:
            assert exc.source is source
            assert exc.target is target
            message = str(exc)
            assert source.value in message
            assert target.value in message
        else:
            raise AssertionError(
                f"expected InvalidTransitionError for {source} -> {target}"
            )
