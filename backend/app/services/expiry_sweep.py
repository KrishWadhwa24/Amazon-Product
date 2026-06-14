"""Expiry sweep scheduler (Requirements 3.4, 3.5, 9.4).

The scanner pool holds SCANNING returns with a 48-hour window. When the window
elapses with no buyer having accepted a deal, the return must leave the pool and
be dispositioned automatically. This module provides that mechanism in two
layers:

* :func:`run_expiry_sweep_once` — the **pure-ish, unit-testable core**: a single
  coroutine that, given an :class:`AsyncSession`, finds every SCANNING return
  whose ``expires_at <= now`` with **no ACCEPTED** MatchCandidate, drives it
  through the lifecycle ``SCANNING -> EXPIRED`` and then auto-routes
  ``EXPIRED -> {NGO_ROUTING | MICROWAREHOUSE}`` per the design's expiry routing
  decision, persisting the computed ``reverse_transit_threshold`` and expiring
  any still-PENDING sibling candidates (Requirement 9.4). It returns the ids of
  the returns it swept.

* :func:`expiry_sweep_loop` / :func:`start_expiry_sweep` /
  :func:`stop_expiry_sweep` — the **long-running background task** wired into the
  FastAPI lifespan. The loop runs on a sub-second cadence (default 500 ms) so the
  EXPIRED transition lands within 1 second of the window elapsing (Requirement
  3.4), removing the return from the discoverable pool (Requirement 3.5). The
  loop is defensive: every iteration runs in its own session and any exception
  (including the database being unavailable) is swallowed so a transient failure
  never crashes the application; the loop simply retries on the next tick.

All status changes go through the shared lifecycle core
(:mod:`app.services.lifecycle`) so the legal transition relation has a single
source of truth.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.enums import MatchStatus, ReturnStatus
from app.models.return_order import ReturnOrder
from app.services.lifecycle import (
    compute_reverse_transit_threshold,
    decide_expiry_route,
    transition,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


async def run_expiry_sweep_once(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> list[int]:
    """Expire and auto-route every due, unmatched SCANNING return once.

    Selects ReturnOrders that are SCANNING with ``expires_at <= now`` and have
    **no ACCEPTED** MatchCandidate, then for each one:

    1. transitions ``SCANNING -> EXPIRED`` via the lifecycle core (Requirements
       3.4, 10.5), removing it from the scanner pool (Requirement 3.5);
    2. computes and persists ``reverse_transit_threshold = cost + ₹150`` and
       auto-routes ``EXPIRED -> NGO_ROUTING`` (price <= threshold) or
       ``EXPIRED -> MICROWAREHOUSE`` (price > threshold) (Requirements 10.9–10.12);
    3. sets every still-PENDING sibling MatchCandidate to EXPIRED (Requirement
       9.4).

    The work is committed once at the end. ``now`` is injectable for
    deterministic testing. Returns the list of swept ReturnOrder ids.
    """
    moment = now or _utcnow()

    stmt = (
        select(ReturnOrder)
        .where(
            ReturnOrder.status == ReturnStatus.SCANNING,
            ReturnOrder.expires_at <= moment,
        )
        .options(
            selectinload(ReturnOrder.product),
            selectinload(ReturnOrder.match_candidates),
        )
    )
    due_returns = list((await session.execute(stmt)).scalars().all())

    swept_ids: list[int] = []
    for return_order in due_returns:
        candidates = return_order.match_candidates

        # A return that already has an ACCEPTED candidate is following the
        # local-delivery path and must not be expired (Requirement 3.4).
        if any(c.status == MatchStatus.ACCEPTED for c in candidates):
            continue

        # SCANNING -> EXPIRED (raises if somehow not permitted; pure core).
        return_order.status = transition(return_order.status, ReturnStatus.EXPIRED)

        product = return_order.product
        # Persist the threshold computed at expiry (Requirement 10.9) and decide
        # the automatic disposition (Requirements 10.10-10.12).
        return_order.reverse_transit_threshold = compute_reverse_transit_threshold(
            product.estimated_reverse_logistics_cost
        )
        route = decide_expiry_route(
            product.price, product.estimated_reverse_logistics_cost
        )
        # EXPIRED -> {NGO_ROUTING | MICROWAREHOUSE} (validated by the core).
        return_order.status = transition(return_order.status, route)

        # Any candidate left PENDING when the return leaves SCANNING is expired
        # (Requirement 9.4).
        for candidate in candidates:
            if candidate.status == MatchStatus.PENDING:
                candidate.status = MatchStatus.EXPIRED

        swept_ids.append(return_order.id)

    if swept_ids:
        await session.commit()

    return swept_ids


async def expiry_sweep_loop(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    interval_seconds: float,
    stop_event: asyncio.Event,
) -> None:
    """Run :func:`run_expiry_sweep_once` on a fixed cadence until stopped.

    Each iteration opens its own session and is wrapped so that **any**
    exception — most importantly the database being unreachable — is logged and
    swallowed rather than propagated, guaranteeing the loop (and therefore the
    app) keeps running and simply retries on the next tick. The loop exits
    promptly when ``stop_event`` is set.
    """
    while not stop_event.is_set():
        try:
            async with sessionmaker() as session:
                await run_expiry_sweep_once(session)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - intentional last-resort guard
            logger.exception("Expiry sweep iteration failed; continuing.")

        # Sleep for the cadence, but wake early if asked to stop.
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass


def start_expiry_sweep(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> tuple[asyncio.Task[None], asyncio.Event] | None:
    """Start the background sweep task if it is enabled in settings.

    Returns the ``(task, stop_event)`` pair when started, or ``None`` when the
    sweep is disabled (the default), so the caller knows whether anything needs
    stopping. Honors the configurable cadence (Requirement 3.4).
    """
    settings = get_settings()
    if not settings.expiry_sweep_enabled:
        return None

    stop_event = asyncio.Event()
    task = asyncio.create_task(
        expiry_sweep_loop(
            sessionmaker,
            interval_seconds=settings.expiry_sweep_interval_seconds,
            stop_event=stop_event,
        ),
        name="expiry-sweep",
    )
    return task, stop_event


async def stop_expiry_sweep(
    handle: tuple[asyncio.Task[None], asyncio.Event] | None,
) -> None:
    """Signal and await shutdown of a sweep started by :func:`start_expiry_sweep`."""
    if handle is None:
        return
    task, stop_event = handle
    stop_event.set()
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass
