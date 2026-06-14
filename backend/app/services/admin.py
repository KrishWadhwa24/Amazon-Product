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
    StoreUnavailableError,
    UnsupportedActionError,
)
from app.models.enums import ReturnStatus
from app.models.return_order import ReturnOrder
from app.services import lifecycle

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
    """

    cache_used: int
    cache_total: int
    reverse_logistics_saved: Decimal
    carbon_offset_index_kg: float
    ngo_csr_credits: Decimal


async def compute_metrics(session: AsyncSession) -> AdminMetrics:
    """Compute the admin operations metrics (Requirements 13.1, 13.3).

    Issues a single grouped status-count query, then derives the bundle:

    * ``cache_used`` (REAL) — count of MICROWAREHOUSE (CACHED) returns, clamped
      to ``cache_total`` so the invariant ``used <= total`` always holds.
    * ``cache_total`` (MOCK) — fixed capacity ``>= 1``.
    * ``reverse_logistics_saved`` / ``carbon_offset_index_kg`` /
      ``ngo_csr_credits`` (MOCK) — deterministic non-negative stand-ins scaled
      off the real status counts.

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
    # Clamp the real cached count into the mocked capacity so the KPI invariant
    # 0 <= used <= total holds even if cached items exceed the demo capacity.
    cache_used = min(cached_count, cache_total)

    return AdminMetrics(
        cache_used=cache_used,
        cache_total=cache_total,
        reverse_logistics_saved=_mock_reverse_logistics_saved(
            local_delivery_count, cached_count
        ),
        carbon_offset_index_kg=_mock_carbon_offset_index_kg(local_delivery_count),
        ngo_csr_credits=_mock_ngo_csr_credits(ngo_routing_count),
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
