"""Analytics counters — the simple active-match tally (Requirement 6.7).

A thin helper over :class:`~app.models.analytics_counter.AnalyticsCounter` that
implements the "increment the active-match count by one" rule the Matching_Engine
must satisfy whenever it creates a PENDING MatchCandidate (Requirement 6.7).

The mechanism is intentionally minimal: one named, get-or-created row holding a
running integer. :func:`increment_active_match_count` bumps it (creating the row
on first use) and :func:`get_active_match_count` reads it back (zero when the row
does not exist yet). Callers run these inside their own transaction; the helpers
``flush`` but never ``commit`` so the increment stays atomic with the match
creation it accompanies.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics_counter import AnalyticsCounter

#: The counter name holding the running count of created PENDING matches.
ACTIVE_MATCH_COUNTER: str = "active_match"


async def _get_or_create(session: AsyncSession, name: str) -> AnalyticsCounter:
    """Return the counter row named ``name``, creating it at zero if absent."""
    stmt = select(AnalyticsCounter).where(AnalyticsCounter.name == name)
    counter = (await session.execute(stmt)).scalar_one_or_none()
    if counter is None:
        counter = AnalyticsCounter(name=name, value=0)
        session.add(counter)
        await session.flush()
    return counter


async def increment_active_match_count(
    session: AsyncSession, *, by: int = 1
) -> int:
    """Increment the active-match counter and return its new value (Req 6.7).

    Creates the counter row on first use. The write is flushed (not committed)
    so it participates in the caller's transaction — the matching engine commits
    the increment together with the new MatchCandidate.
    """
    counter = await _get_or_create(session, ACTIVE_MATCH_COUNTER)
    counter.value += by
    await session.flush()
    return counter.value


async def get_active_match_count(session: AsyncSession) -> int:
    """Return the current active-match count (zero when never incremented)."""
    stmt = select(AnalyticsCounter).where(
        AnalyticsCounter.name == ACTIVE_MATCH_COUNTER
    )
    counter = (await session.execute(stmt)).scalar_one_or_none()
    return counter.value if counter is not None else 0
