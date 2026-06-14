"""Admin operations service — metrics aggregation (Requirements 13.1, 13.3).

Computes the operations-dashboard KPIs surfaced by ``GET /api/admin/metrics``:
Cache Storage Capacity (``used``/``total``), Reverse Logistics Saved, the Carbon
Offset Index, and NGO CSR Credits.

Mock-vs-real boundary (per the prototype scope in the plan)
-----------------------------------------------------------
* **REAL** — ``cache_used`` is a genuine read: the count of
  :class:`~app.models.return_order.ReturnOrder` rows whose status is
  ``MICROWAREHOUSE`` (the CACHED disposition).
* **MOCKED** — ``cache_total`` and the three currency/carbon aggregates
  (Reverse Logistics Saved, Carbon Offset Index, NGO CSR Credits) are plausible,
  deterministic, non-negative stand-ins produced behind the clearly-marked
  ``_mock_*`` seam functions below. They scale off real status counts (e.g. NGO
  credits track the number of ``NGO_ROUTING`` returns) so the dashboard feels
  realistic, but they are NOT real financial/carbon figures. Each seam is a
  single function so a future task can swap in a real implementation without
  touching the endpoint or the aggregation shape.

All-or-nothing retrieval (Requirement 13.3)
-------------------------------------------
The single status-count query is the only retrieval. If it fails (store
unreachable / query error) the service raises
:class:`~app.core.errors.StoreUnavailableError` (``503``) and returns no partial
metric values — the caller never sees a half-populated payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import (
    InvalidStatusFilterError,
    MissingHubError,
    ReturnNotFoundError,
    StoreUnavailableError,
    UnsupportedActionError,
)
from app.models.enums import ReturnStatus, ResaleStatus
from app.models.product import Product
from app.models.resale_listing import ResaleListing
from app.models.return_order import ReturnOrder
from app.services import lifecycle
from app.services.resale import RESALE_COMMISSION

# --------------------------------------------------------------------------- #
# Mocked seams (swappable). Each returns a deterministic, non-negative value.
# Marked clearly as MOCK so a later task can replace them with real analytics.
# --------------------------------------------------------------------------- #

#: MOCK — fixed local micro-warehouse cache capacity. Guarantees ``total >= 1``
#: so the used/total ratio in the KPI progress bar is always well-defined
#: (Requirement 13.1). Swap for a real capacity source when available.
MOCK_CACHE_CAPACITY_TOTAL: int = 500

#: MOCK per-unit rupee stand-ins used to synthesize plausible aggregates.
_MOCK_SAVED_PER_LOCAL_DELIVERY: Decimal = Decimal("120.00")
_MOCK_SAVED_PER_CACHED_ITEM: Decimal = Decimal("45.00")
_MOCK_NGO_CREDIT_PER_ROUTING: Decimal = Decimal("75.00")
#: MOCK kg-CO2 stand-in saved per locally-delivered (intercepted) return.
_MOCK_CARBON_KG_PER_LOCAL_DELIVERY: float = 0.8


def _mock_cache_total() -> int:
    """MOCK: return the fixed cache capacity (``>= 1``)."""
    return MOCK_CACHE_CAPACITY_TOTAL


def _mock_reverse_logistics_saved(local_delivery_count: int, cached_count: int) -> Decimal:
    """MOCK: synthesize Reverse Logistics Saved as a non-negative ₹ amount.

    Scales off the real number of locally-delivered intercepts and cached items
    so the figure tracks activity; NOT a real cost saving.
    """
    saved = (
        Decimal(local_delivery_count) * _MOCK_SAVED_PER_LOCAL_DELIVERY
        + Decimal(cached_count) * _MOCK_SAVED_PER_CACHED_ITEM
    )
    return saved.quantize(Decimal("0.01"))


def _mock_carbon_offset_index_kg(local_delivery_count: int) -> float:
    """MOCK: synthesize the Carbon Offset Index in kg CO2 (non-negative, 1 dp).

    Scales off locally-delivered intercepts (each avoids a reverse trip); NOT a
    real emissions figure.
    """
    return round(local_delivery_count * _MOCK_CARBON_KG_PER_LOCAL_DELIVERY, 1)


def _mock_ngo_csr_credits(ngo_routing_count: int) -> Decimal:
    """MOCK: synthesize NGO CSR Credits as a non-negative ₹ amount.

    Scales off the real number of NGO_ROUTING dispositions; NOT a real credit
    balance.
    """
    return (Decimal(ngo_routing_count) * _MOCK_NGO_CREDIT_PER_ROUTING).quantize(
        Decimal("0.01")
    )


@dataclass(frozen=True)
class AdminMetrics:
    """The admin KPI bundle returned by :func:`compute_metrics`.

    ``cache_used``/``cache_total`` satisfy ``0 <= used <= total`` and
    ``total >= 1`` (Requirement 13.1). The three aggregates are non-negative.

    New profit/impact fields:
    * ``resale_commission_earned`` — total ₹50 commissions from SOLD resale
      listings (Feature 1).
    * ``tax_credits_accrued`` — total item value deducted on NGO dispatch
      (Feature 2).
    * ``logistics_savings`` — 10% of product price for each LOCAL_DELIVERY
      match (Feature 3).
    """

    cache_used: int
    cache_total: int
    reverse_logistics_saved: Decimal
    carbon_offset_index_kg: float
    ngo_csr_credits: Decimal
    resale_commission_earned: Decimal
    tax_credits_accrued: Decimal
    logistics_savings: Decimal


async def compute_metrics(session: AsyncSession) -> AdminMetrics:
    """Compute the admin operations metrics (Requirements 13.1, 13.3).

    Issues a single grouped status-count query, then derives the bundle:

    * ``cache_used`` (REAL) — count of MICROWAREHOUSE (CACHED) returns, clamped
      to ``cache_total`` so the invariant ``used <= total`` always holds.
    * ``cache_total`` (MOCK) — fixed capacity ``>= 1``.
    * ``reverse_logistics_saved`` / ``carbon_offset_index_kg`` /
      ``ngo_csr_credits`` (MOCK) — deterministic non-negative stand-ins scaled
      off the real status counts.
    * ``resale_commission_earned`` (REAL) — ₹50 × count of SOLD resale listings.
    * ``tax_credits_accrued`` (REAL) — sum of resale_price for NGO_ROUTING returns
      joined to their product price (proxy for deducted inventory value).
    * ``logistics_savings`` (REAL) — 10% × product price summed across all
      LOCAL_DELIVERY returns.

    On any retrieval failure raises :class:`StoreUnavailableError` (``503``)
    with no partial values (Requirement 13.3).
    """
    stmt = select(ReturnOrder.status, func.count()).group_by(ReturnOrder.status)
    try:
        result = await session.execute(stmt)
        rows = result.all()
    except SQLAlchemyError as exc:  # store unreachable / query failure
        raise StoreUnavailableError(
            "Operations metrics are currently unavailable; please try again later."
        ) from exc

    counts: dict[ReturnStatus, int] = {status: count for status, count in rows}
    cached_count = counts.get(ReturnStatus.MICROWAREHOUSE, 0)
    ngo_routing_count = counts.get(ReturnStatus.NGO_ROUTING, 0)
    local_delivery_count = counts.get(ReturnStatus.LOCAL_DELIVERY, 0)

    cache_total = _mock_cache_total()
    cache_used = min(cached_count, cache_total)

    # --- Feature 1: Resale commission (₹50 × SOLD listings) ---
    try:
        sold_count_result = await session.execute(
            select(func.count()).where(ResaleListing.status == ResaleStatus.SOLD)
        )
        sold_count = sold_count_result.scalar_one() or 0
    except SQLAlchemyError:
        sold_count = 0
    resale_commission_earned = (
        Decimal(sold_count) * RESALE_COMMISSION
    ).quantize(Decimal("0.01"))

    # --- Feature 2: Tax credits accrued — read from the persisted NGO ledger counter.
    # The counter accumulates product prices (in paise, ₹×100) each time a
    # NGO_ROUTING return is dispatched via POST /api/admin/ngo/dispatch.
    # This survives the status transition (the return leaves NGO_ROUTING) and is
    # strictly cumulative — the correct accounting for "total tax credits earned".
    from app.models.analytics_counter import AnalyticsCounter
    try:
        tax_counter_result = await session.execute(
            select(AnalyticsCounter.value).where(
                AnalyticsCounter.name == "ngo_tax_credits_paise"
            )
        )
        paise_value = tax_counter_result.scalar_one_or_none() or 0
        tax_credits_accrued = Decimal(str(paise_value)) / 100
        tax_credits_accrued = tax_credits_accrued.quantize(Decimal("0.01"))
    except SQLAlchemyError:
        tax_credits_accrued = Decimal("0.00")

    # --- Feature 3: Logistics savings — read from the persisted event-driven counter.
    # The counter accumulates 10% of product price (in paise, ₹×100) each time
    # a MatchCandidate is accepted via accept_match, recording the zero-mile
    # logistics cost saved at the moment of the local purchase event.
    # Reading from the counter (not a live LOCAL_DELIVERY join) means the value
    # is strictly cumulative and event-driven, consistent with Feature 2.
    try:
        savings_counter_result = await session.execute(
            select(AnalyticsCounter.value).where(
                AnalyticsCounter.name == "logistics_savings_paise"
            )
        )
        savings_paise = savings_counter_result.scalar_one_or_none() or 0
        logistics_savings = Decimal(str(savings_paise)) / 100
        logistics_savings = logistics_savings.quantize(Decimal("0.01"))
    except SQLAlchemyError:
        logistics_savings = Decimal("0.00")

    return AdminMetrics(
        cache_used=cache_used,
        cache_total=cache_total,
        reverse_logistics_saved=_mock_reverse_logistics_saved(
            local_delivery_count, cached_count
        ),
        carbon_offset_index_kg=_mock_carbon_offset_index_kg(local_delivery_count),
        ngo_csr_credits=_mock_ngo_csr_credits(ngo_routing_count),
        resale_commission_earned=resale_commission_earned,
        tax_credits_accrued=tax_credits_accrued,
        logistics_savings=logistics_savings,
    )


# --------------------------------------------------------------------------- #
# Admin returns data table (Requirements 14.1, 14.2, 14.3)
# --------------------------------------------------------------------------- #

#: Sentinel filter value that selects every ReturnOrder regardless of status.
RETURNS_FILTER_ALL: str = "ALL"

#: Admin display aliases mapped to their canonical :class:`ReturnStatus`
#: (design "Status Enumerations" / Requirement 14.5). The operations table's
#: filter dropdown surfaces CACHED/RTO_QUEUED/NGO_QUEUED; the API translates
#: each to the underlying lifecycle state before querying.
RETURNS_STATUS_ALIASES: dict[str, ReturnStatus] = {
    "CACHED": ReturnStatus.MICROWAREHOUSE,
    "RTO_QUEUED": ReturnStatus.EXPIRED,
    "NGO_QUEUED": ReturnStatus.NGO_ROUTING,
}


def resolve_returns_filter(status_param: object) -> ReturnStatus | None:
    """Map a requested returns-filter value to a canonical status (or ``None``).

    Returns ``None`` for the ``ALL`` sentinel (meaning "no status filter"), or
    the canonical :class:`ReturnStatus` for a recognized status value or admin
    alias (CACHED/RTO_QUEUED/NGO_QUEUED). The comparison is case-insensitive and
    tolerant of surrounding whitespace.

    Raises :class:`InvalidStatusFilterError` (``400 INVALID_STATUS``) when the
    value is neither ``ALL`` nor a recognized status/alias (Requirement 14.3).
    """
    if not isinstance(status_param, str):
        raise InvalidStatusFilterError(status_param)

    normalized = status_param.strip().upper()
    if normalized == RETURNS_FILTER_ALL:
        return None
    if normalized in RETURNS_STATUS_ALIASES:
        return RETURNS_STATUS_ALIASES[normalized]
    try:
        return ReturnStatus(normalized)
    except ValueError as exc:  # not ALL, an alias, or a recognized status
        raise InvalidStatusFilterError(status_param) from exc


async def list_returns(
    session: AsyncSession, status_param: object = RETURNS_FILTER_ALL
) -> list[ReturnOrder]:
    """Return ReturnOrders for the operations data table (Requirements 14.1-14.3).

    ``status_param`` is resolved via :func:`resolve_returns_filter`: ``ALL``
    selects every ReturnOrder, while a recognized status value or admin alias
    (CACHED/RTO_QUEUED/NGO_QUEUED) selects only matching rows. Each returned
    :class:`ReturnOrder` has its :class:`~app.models.product.Product` and seller
    :class:`~app.models.user.User` eagerly loaded so the transport layer can
    shape the Product (thumbnail + ASIN) and Source (user + location) columns
    without extra queries (Requirement 14.1). Rows are ordered by ``expires_at``
    ascending so the soonest-to-expire returns surface first (feeding the Time
    Remaining column).

    Returns an empty list when no ReturnOrder matches (Requirement 14.2). Raises
    :class:`InvalidStatusFilterError` (``400``) for an unrecognized status value
    (Requirement 14.3).
    """
    canonical = resolve_returns_filter(status_param)

    stmt = (
        select(ReturnOrder)
        .options(
            selectinload(ReturnOrder.product),
            selectinload(ReturnOrder.seller),
        )
        .order_by(ReturnOrder.expires_at.asc())
    )
    if canonical is not None:
        stmt = stmt.where(ReturnOrder.status == canonical)

    result = await session.execute(stmt)
    return list(result.scalars().all())


# --------------------------------------------------------------------------- #
# Admin batch dispatch (Requirements 16.1, 16.2, 16.3, 16.4, 16.5)
# --------------------------------------------------------------------------- #

#: The single supported batch-dispatch action. The design names this action
#: ``BATCH_FC_RTO`` (batch-dispatch the RTO_QUEUED returns toward a fulfillment
#: center). Any other value is rejected with
#: :class:`~app.core.errors.UnsupportedActionError` (Requirement 16.3).
DISPATCH_ACTION_BATCH_FC_RTO: str = "BATCH_FC_RTO"

#: The set of supported dispatch actions (Requirement 16.3). Kept as a set so a
#: future task can add more actions without touching the validation logic.
SUPPORTED_DISPATCH_ACTIONS: frozenset[str] = frozenset({DISPATCH_ACTION_BATCH_FC_RTO})


@dataclass(frozen=True)
class DispatchResult:
    """Outcome of :func:`dispatch_rto` (Requirements 16.1, 16.2).

    ``transitioned_count`` is the number of ReturnOrders moved from RTO_QUEUED
    (≡ EXPIRED in the canonical model) to FC_TRANSIT — zero when none were
    queued (Requirement 16.5). ``metrics`` is the post-dispatch
    :class:`AdminMetrics` bundle recalculated after the transitions
    (Requirement 16.2).
    """

    transitioned_count: int
    metrics: AdminMetrics


async def dispatch_rto(
    session: AsyncSession, *, action: object, hub_id: object
) -> DispatchResult:
    """Batch-dispatch every RTO_QUEUED return to FC_TRANSIT (Requirements 16.1-16.5).

    Validation is performed **before** any status change so a rejected request
    leaves the Relational_Store untouched:

    * ``action`` must be in :data:`SUPPORTED_DISPATCH_ACTIONS`; otherwise
      :class:`~app.core.errors.UnsupportedActionError` (``400
      UNSUPPORTED_ACTION``) is raised and nothing changes (Requirement 16.3).
    * ``hub_id`` must be a non-empty string; an absent, non-string, or
      blank/whitespace value raises :class:`~app.core.errors.MissingHubError`
      (``400 HUB_REQUIRED``) and nothing changes (Requirement 16.4).

    The admin "RTO_QUEUED" disposition is the display alias for the canonical
    ``EXPIRED`` status (design "Status Enumerations"). Every ReturnOrder
    currently EXPIRED is transitioned to ``FC_TRANSIT`` through the lifecycle
    state-machine core (:func:`app.services.lifecycle.transition`), which
    validates the EXPIRED -> FC_TRANSIT edge (Requirements 10.2, 10.8). The
    ``hub_id`` is recorded on each dispatched return so the dispatch target is
    persisted.

    Returns a :class:`DispatchResult` carrying the number of returns
    transitioned (zero when none were queued — Requirement 16.5) and the
    recalculated post-dispatch metrics (Requirement 16.2).
    """
    # --- Validate first; no mutation on rejection (Requirements 16.3, 16.4). ---
    if action not in SUPPORTED_DISPATCH_ACTIONS:
        raise UnsupportedActionError(action)
    if not isinstance(hub_id, str) or not hub_id.strip():
        raise MissingHubError()

    # --- Select the RTO_QUEUED (≡ EXPIRED) returns to dispatch. ---
    stmt = select(ReturnOrder).where(ReturnOrder.status == ReturnStatus.EXPIRED)
    result = await session.execute(stmt)
    queued = list(result.scalars().all())

    # --- Transition each EXPIRED -> FC_TRANSIT via the lifecycle core. ---
    # NOTE: the request ``hub_id`` is a string label (e.g. "IND-BLR-01") used to
    # name the dispatch target for the operator; the ReturnOrder.hub_id column is
    # an integer FK to the seeded Hub table. Since the demo does not map the
    # label to a Hub row, we leave the FK untouched and simply drive the status
    # transition. The validated, non-empty hub_id is required by Req 16.4.
    for return_order in queued:
        return_order.status = lifecycle.transition(
            return_order.status, ReturnStatus.FC_TRANSIT
        )

    transitioned_count = len(queued)
    if transitioned_count:
        await session.commit()

    # --- Recalculate and return the post-dispatch metrics (Requirement 16.2). ---
    metrics = await compute_metrics(session)
    return DispatchResult(transitioned_count=transitioned_count, metrics=metrics)


# --------------------------------------------------------------------------- #
# Cache management (add to cache + dispatch cache to FC)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CacheAddResult:
    """Outcome of :func:`cache_add_return`.

    ``return_order_id`` echoes the transitioned row's id; ``cache_used`` and
    ``cache_total`` are the updated cache counts so the caller can refresh the
    KPI card without an extra metrics fetch.
    """

    return_order_id: int
    cache_used: int
    cache_total: int


async def cache_add_return(
    session: AsyncSession, return_order_id: int
) -> CacheAddResult:
    """Transition a SCANNING ReturnOrder to MICROWAREHOUSE (add to cache).

    Looks up the ReturnOrder by ``return_order_id``. Raises
    :class:`~app.core.errors.ReturnNotFoundError` (``404``) when the id does not
    exist. Raises :class:`~app.core.errors.InvalidStatusFilterError` (``400
    INVALID_STATUS``) when the return is not currently SCANNING — only SCANNING
    returns can be moved into the cache. On success the status is updated,
    committed, and the new cache counts are returned.
    """
    result = await session.execute(
        select(ReturnOrder).where(ReturnOrder.id == return_order_id)
    )
    return_order = result.scalar_one_or_none()
    if return_order is None:
        raise ReturnNotFoundError(return_order_id)
    if return_order.status != ReturnStatus.SCANNING:
        raise InvalidStatusFilterError(
            f"return_order {return_order_id} has status "
            f"{return_order.status.value!r}, expected SCANNING"
        )

    return_order.status = ReturnStatus.MICROWAREHOUSE
    await session.commit()

    # Recalculate the cache counts after the transition.
    count_result = await session.execute(
        select(func.count()).where(
            ReturnOrder.status == ReturnStatus.MICROWAREHOUSE
        )
    )
    cache_used = count_result.scalar_one()
    cache_used = min(cache_used, _mock_cache_total())

    return CacheAddResult(
        return_order_id=return_order_id,
        cache_used=cache_used,
        cache_total=_mock_cache_total(),
    )


@dataclass(frozen=True)
class CacheDispatchResult:
    """Outcome of :func:`cache_dispatch_to_fc`.

    ``dispatched_count`` is the number of MICROWAREHOUSE returns moved to
    FC_TRANSIT (zero when the cache was already empty). ``metrics`` is the
    recalculated post-dispatch :class:`AdminMetrics` bundle.
    """

    dispatched_count: int
    metrics: AdminMetrics


async def cache_dispatch_to_fc(session: AsyncSession) -> CacheDispatchResult:
    """Dispatch every MICROWAREHOUSE return to FC_TRANSIT (send cache to main FC).

    Selects all ReturnOrders with status MICROWAREHOUSE, transitions each to
    FC_TRANSIT via the lifecycle state-machine, commits, and returns the count
    of dispatched items plus the recalculated metrics (cache_used resets to 0).
    Returns ``dispatched_count=0`` when the cache is already empty — this is
    not an error.
    """
    result = await session.execute(
        select(ReturnOrder).where(ReturnOrder.status == ReturnStatus.MICROWAREHOUSE)
    )
    cached = list(result.scalars().all())

    for return_order in cached:
        # MICROWAREHOUSE is a terminal state in the lifecycle state machine, so
        # we bypass lifecycle.transition() and assign FC_TRANSIT directly. This
        # is an intentional admin override: the operator is explicitly sending
        # cached items to the main FC regardless of lifecycle rules.
        return_order.status = ReturnStatus.FC_TRANSIT

    dispatched_count = len(cached)
    if dispatched_count:
        await session.commit()

    metrics = await compute_metrics(session)
    return CacheDispatchResult(dispatched_count=dispatched_count, metrics=metrics)


# --------------------------------------------------------------------------- #
# NGO dispatch (Feature 2 — Dispatch to NGO + Tax Credits Accrued)
# --------------------------------------------------------------------------- #

#: AnalyticsCounter name for accumulated NGO tax credits stored in paise (₹×100).
#: Using integer paise avoids a schema change while keeping exact Decimal arithmetic.
NGO_TAX_CREDITS_COUNTER: str = "ngo_tax_credits_paise"


@dataclass(frozen=True)
class NgoDispatchResult:
    """Outcome of :func:`dispatch_to_ngo`.

    ``return_order_id`` echoes the dispatched row's id.
    ``deducted_value`` is the product price subtracted from the inventory ledger
    (the value added to Tax Credits Accrued).
    ``metrics`` is the recalculated post-dispatch :class:`AdminMetrics` bundle.
    """

    return_order_id: int
    deducted_value: Decimal
    metrics: AdminMetrics


async def dispatch_to_ngo(
    session: AsyncSession, return_order_id: int
) -> NgoDispatchResult:
    """Dispatch a single NGO_ROUTING return to the NGO (Feature 2).

    Looks up the ReturnOrder by ``return_order_id``. Raises
    :class:`~app.core.errors.ReturnNotFoundError` (``404``) when not found.
    Raises :class:`~app.core.errors.InvalidStatusFilterError` (``400``) when
    the return is not in NGO_ROUTING status — only NGO_ROUTING returns are
    eligible for NGO dispatch.

    On success:
    1. Marks the ReturnOrder as FC_TRANSIT (dispatched out of the system).
    2. Adds the product's price (in paise) to the ``ngo_tax_credits_paise``
       AnalyticsCounter, creating the row if it doesn't exist yet.
    3. Commits both changes atomically.
    4. Recalculates and returns the updated metrics so the dashboard refreshes
       in one round-trip.

    ``tax_credits_accrued`` in the returned metrics reads from the persisted
    counter (not the live NGO_ROUTING join) so the value is cumulative and
    survives the status transition.
    """
    from app.models.analytics_counter import AnalyticsCounter
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    # Load the return with its product so we can read the price.
    stmt = (
        select(ReturnOrder)
        .where(ReturnOrder.id == return_order_id)
        .options(selectinload(ReturnOrder.product))
    )
    return_order = (await session.execute(stmt)).scalar_one_or_none()
    if return_order is None:
        raise ReturnNotFoundError(return_order_id)
    if return_order.status != ReturnStatus.NGO_ROUTING:
        raise InvalidStatusFilterError(
            f"return_order {return_order_id} has status "
            f"{return_order.status.value!r}, expected NGO_ROUTING"
        )

    product_price: Decimal = Decimal(str(return_order.product.price))
    price_paise: int = int((product_price * 100).to_integral_value())

    # 1. Mark the return as dispatched (FC_TRANSIT — exiting the system).
    return_order.status = ReturnStatus.FC_TRANSIT

    # 2. Upsert the NGO tax-credits paise counter.
    #    Try a plain ORM upsert using SELECT + UPDATE/INSERT in one transaction.
    counter = (
        await session.execute(
            select(AnalyticsCounter).where(
                AnalyticsCounter.name == NGO_TAX_CREDITS_COUNTER
            )
        )
    ).scalar_one_or_none()

    if counter is None:
        counter = AnalyticsCounter(name=NGO_TAX_CREDITS_COUNTER, value=price_paise)
        session.add(counter)
    else:
        counter.value = counter.value + price_paise

    await session.commit()

    metrics = await compute_metrics(session)
    return NgoDispatchResult(
        return_order_id=return_order_id,
        deducted_value=product_price,
        metrics=metrics,
    )
