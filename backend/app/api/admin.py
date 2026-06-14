"""Admin operations router (Requirements 13-16).

Hosts the operations-dashboard read/dispatch endpoints. This module starts with
``GET /api/admin/metrics`` (task 23.1) and will gain the returns data table
(task 24.1) and batch dispatch (task 24.6) endpoints; it is structured so those
can be added alongside without disturbing the other routers.

The admin reads are intentionally **public/open** for the demo: the design's
admin endpoints are unauthenticated dashboard reads and the tasks specify no
auth requirement for admin. If access control is needed later it can be added
via a dependency on these routes without changing the service layer.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models.enums import ReturnStatus
from app.services import admin as admin_service

router = APIRouter(prefix="/api/admin", tags=["admin"])

class AdminMetricsResponse(BaseModel):
    """``200`` payload for ``GET /api/admin/metrics`` (Requirement 13.1).

    ``cache_used``/``cache_total`` satisfy ``0 <= used <= total`` and
    ``total >= 1``; the three aggregates are non-negative. ``cache_used`` is a
    real read (MICROWAREHOUSE/CACHED count) while ``cache_total`` and the
    aggregates are mocked plausible stand-ins (see the admin service).

    New profit/impact fields (Features 1-3):
    * ``resale_commission_earned`` — ₹50 × SOLD resale listing count.
    * ``tax_credits_accrued`` — sum of product prices for NGO_ROUTING returns.
    * ``logistics_savings`` — 10% × product price for LOCAL_DELIVERY returns.
    """

    cache_used: int
    cache_total: int
    reverse_logistics_saved: Decimal
    carbon_offset_index_kg: float
    ngo_csr_credits: Decimal
    resale_commission_earned: Decimal
    tax_credits_accrued: Decimal
    logistics_savings: Decimal


@router.get(
    "/metrics",
    response_model=AdminMetricsResponse,
    summary="Operations dashboard KPIs (cache capacity + impact aggregates)",
)
async def get_metrics(
    session: AsyncSession = Depends(get_session),
) -> AdminMetricsResponse:
    """Return the admin operations metrics bundle (Requirements 13.1, 13.3).

    Delegates to :func:`app.services.admin.compute_metrics`. On any retrieval
    failure the service raises
    :class:`~app.core.errors.StoreUnavailableError`, which the application's
    domain-error handler renders as ``503 STORE_UNAVAILABLE`` with no partial
    metric values (Requirement 13.3).
    """
    metrics = await admin_service.compute_metrics(session)
    return _metrics_response(metrics)


def _metrics_response(metrics: "admin_service.AdminMetrics") -> AdminMetricsResponse:
    """Convert an :class:`~app.services.admin.AdminMetrics` to the API response model."""
    return AdminMetricsResponse(
        cache_used=metrics.cache_used,
        cache_total=metrics.cache_total,
        reverse_logistics_saved=metrics.reverse_logistics_saved,
        carbon_offset_index_kg=metrics.carbon_offset_index_kg,
        ngo_csr_credits=metrics.ngo_csr_credits,
        resale_commission_earned=metrics.resale_commission_earned,
        tax_credits_accrued=metrics.tax_credits_accrued,
        logistics_savings=metrics.logistics_savings,
    )


class ReturnRowProductResource(BaseModel):
    """Product fields for the operations table's Product column (Req 14.4).

    Carries the catalog ``name`` plus the official ``image_url`` and the
    optional ``uploaded_image_path`` so the frontend can render the product
    thumbnail (preferring an uploaded image, falling back to ``image_url``).
    """

    model_config = ConfigDict(from_attributes=True)

    name: str
    image_url: str
    uploaded_image_path: str | None = None


class ReturnRowSourceResource(BaseModel):
    """Seller (Source) fields for the operations table (Requirement 14.4).

    Surfaces the seller's display name and geographic coordinates so the Source
    column can show the originating user and their location.
    """

    user_name: str
    latitude: float
    longitude: float


class AdminReturnRowResource(BaseModel):
    """One row of the admin operations returns table (Requirement 14.1).

    Joins each :class:`~app.models.return_order.ReturnOrder` with its Product and
    seller User, exposing exactly the fields the OperationsDataTable columns
    consume: ID, Product (thumbnail + ASIN), Source (user + location), Status
    badge, and Time Remaining (derived client-side from ``expires_at``).
    """

    id: int
    status: ReturnStatus
    asin: str
    product: ReturnRowProductResource
    source: ReturnRowSourceResource
    initiated_at: datetime
    expires_at: datetime


@router.get(
    "/returns",
    response_model=list[AdminReturnRowResource],
    summary="List ReturnOrders for the operations data table (status-filtered)",
)
async def get_returns(
    status: str = Query(
        default=admin_service.RETURNS_FILTER_ALL,
        description=(
            "Filter by ALL, a recognized ReturnOrder status, or an admin alias "
            "(CACHED, RTO_QUEUED, NGO_QUEUED)."
        ),
    ),
    session: AsyncSession = Depends(get_session),
) -> list[AdminReturnRowResource]:
    """Return ReturnOrders for the operations table (Requirements 14.1-14.3).

    ``status`` accepts ``ALL`` (all returns), a recognized ReturnOrder status,
    or an admin display alias (CACHED≡MICROWAREHOUSE, RTO_QUEUED≡EXPIRED,
    NGO_QUEUED≡NGO_ROUTING). Each row is joined with its Product and seller User
    (Requirement 14.1); no match yields an empty array (Requirement 14.2). An
    unrecognized value makes the service raise
    :class:`~app.core.errors.InvalidStatusFilterError`, which the domain-error
    handler renders as ``400 INVALID_STATUS`` with no return data
    (Requirement 14.3). This is a public dashboard read like the metrics
    endpoint.
    """
    rows = await admin_service.list_returns(session, status)
    return [
        AdminReturnRowResource(
            id=row.id,
            status=row.status,
            asin=row.asin,
            product=ReturnRowProductResource.model_validate(row.product),
            source=ReturnRowSourceResource(
                user_name=row.seller.name,
                latitude=row.seller.latitude,
                longitude=row.seller.longitude,
            ),
            initiated_at=row.initiated_at,
            expires_at=row.expires_at,
        )
        for row in rows
    ]


class DispatchRequest(BaseModel):
    """Request body for ``POST /api/admin/dispatch`` (Requirements 16.1, 16.3, 16.4).

    ``action`` selects the dispatch operation (the design's supported action is
    ``BATCH_FC_RTO``); ``hub_id`` names the fulfillment hub the queued returns
    are dispatched to. Both are validated in the service layer so the endpoint
    can surface the precise domain error (``UNSUPPORTED_ACTION`` /
    ``HUB_REQUIRED``) rather than a generic ``422``. They are typed loosely
    (``str | None``) here for the same reason: validation belongs to the service
    so a missing/blank value maps to the documented ``400 HUB_REQUIRED`` rather
    than a Pydantic ``422``.
    """

    action: str | None = None
    hub_id: str | None = None


class DispatchResponse(BaseModel):
    """``200`` payload for ``POST /api/admin/dispatch`` (Requirements 16.1, 16.2).

    ``transitioned_count`` is the number of RTO_QUEUED returns moved to
    FC_TRANSIT (zero when none were queued, Requirement 16.5); ``metrics`` is the
    recalculated post-dispatch KPI bundle (Requirement 16.2).
    """

    transitioned_count: int
    metrics: AdminMetricsResponse


@router.post(
    "/dispatch",
    response_model=DispatchResponse,
    summary="Batch-dispatch RTO_QUEUED returns to a fulfillment hub",
)
async def dispatch_returns(
    body: DispatchRequest,
    session: AsyncSession = Depends(get_session),
) -> DispatchResponse:
    """Batch-dispatch queued returns to a hub (Requirements 16.1-16.5).

    Delegates to :func:`app.services.admin.dispatch_rto`, which validates the
    ``action`` and ``hub_id`` before any mutation: an unsupported action raises
    :class:`~app.core.errors.UnsupportedActionError` (``400 UNSUPPORTED_ACTION``,
    Requirement 16.3) and an absent/empty hub identifier raises
    :class:`~app.core.errors.MissingHubError` (``400 HUB_REQUIRED``,
    Requirement 16.4) — in both cases no ReturnOrder status changes. On success
    every RTO_QUEUED (≡ EXPIRED) return is transitioned to FC_TRANSIT and the
    transitioned count plus recalculated metrics are returned (Requirements
    16.1, 16.2, 16.5). Like the other admin routes this is a public dashboard
    operation.
    """
    outcome = await admin_service.dispatch_rto(
        session, action=body.action, hub_id=body.hub_id
    )
    return DispatchResponse(
        transitioned_count=outcome.transitioned_count,
        metrics=_metrics_response(outcome.metrics),
    )


# --------------------------------------------------------------------------- #
# Cache management endpoints
# --------------------------------------------------------------------------- #


class CacheAddRequest(BaseModel):
    """Request body for ``POST /api/admin/cache/add``.

    ``return_order_id`` identifies the SCANNING ReturnOrder to move into the
    local micro-warehouse cache (MICROWAREHOUSE status).
    """

    return_order_id: int


class CacheAddResponse(BaseModel):
    """``200`` payload for ``POST /api/admin/cache/add``.

    Returns the updated cache counts so the frontend KPI card refreshes
    immediately without a separate metrics fetch.
    """

    return_order_id: int
    cache_used: int
    cache_total: int


@router.post(
    "/cache/add",
    response_model=CacheAddResponse,
    summary="Move a SCANNING return into the local micro-warehouse cache",
)
async def cache_add(
    body: CacheAddRequest,
    session: AsyncSession = Depends(get_session),
) -> CacheAddResponse:
    """Transition a SCANNING ReturnOrder to MICROWAREHOUSE (cached).

    Looks up the ReturnOrder by ``return_order_id``, validates it is currently
    SCANNING, transitions it to MICROWAREHOUSE, commits, and returns the updated
    cache counts. Raises ``404 NOT_FOUND`` when the id does not exist and
    ``400 INVALID_STATUS`` when the return is not in SCANNING state.
    """
    result = await admin_service.cache_add_return(session, body.return_order_id)
    return CacheAddResponse(
        return_order_id=result.return_order_id,
        cache_used=result.cache_used,
        cache_total=result.cache_total,
    )


class CacheDispatchResponse(BaseModel):
    """``200`` payload for ``POST /api/admin/cache/dispatch``.

    ``dispatched_count`` is the number of MICROWAREHOUSE returns moved to
    FC_TRANSIT (zero when the cache was already empty). ``metrics`` is the
    recalculated post-dispatch KPI bundle so the dashboard refreshes in one
    round-trip.
    """

    dispatched_count: int
    metrics: AdminMetricsResponse


@router.post(
    "/cache/dispatch",
    response_model=CacheDispatchResponse,
    summary="Dispatch all cached (MICROWAREHOUSE) returns to the main FC",
)
async def cache_dispatch(
    session: AsyncSession = Depends(get_session),
) -> CacheDispatchResponse:
    """Transition every MICROWAREHOUSE return to FC_TRANSIT (dispatch to FC).

    Selects all ReturnOrders with status MICROWAREHOUSE, moves each to
    FC_TRANSIT, commits, and returns the count of dispatched items plus the
    recalculated metrics (cache_used resets to 0). Returns ``dispatched_count=0``
    when the cache is already empty — this is not an error.
    """
    result = await admin_service.cache_dispatch_to_fc(session)
    return CacheDispatchResponse(
        dispatched_count=result.dispatched_count,
        metrics=_metrics_response(result.metrics),
    )


# --------------------------------------------------------------------------- #
# NGO dispatch endpoint (Feature 2)
# --------------------------------------------------------------------------- #


class NgoDispatchRequest(BaseModel):
    """Request body for ``POST /api/admin/ngo/dispatch``.

    ``return_order_id`` identifies the NGO_ROUTING ReturnOrder to dispatch to
    the NGO charity partner.
    """

    return_order_id: int


class NgoDispatchResponse(BaseModel):
    """``200`` payload for ``POST /api/admin/ngo/dispatch``.

    ``return_order_id`` echoes the dispatched row's id.
    ``deducted_value`` is the product price subtracted from the inventory ledger
    and added to the Tax Credits Accrued metric.
    ``metrics`` is the recalculated post-dispatch KPI bundle so the dashboard
    refreshes in one round-trip.
    """

    return_order_id: int
    deducted_value: Decimal
    metrics: AdminMetricsResponse


@router.post(
    "/ngo/dispatch",
    response_model=NgoDispatchResponse,
    summary="Dispatch a NGO_ROUTING return to the NGO and record tax credit",
)
async def ngo_dispatch(
    body: NgoDispatchRequest,
    session: AsyncSession = Depends(get_session),
) -> NgoDispatchResponse:
    """Dispatch a single NGO_ROUTING return to the NGO charity partner.

    Looks up the ReturnOrder, validates it is NGO_ROUTING (``400`` otherwise,
    ``404`` if not found), marks it as dispatched (FC_TRANSIT), and adds the
    product's price to the cumulative Tax Credits Accrued ledger. Returns the
    deducted value and the recalculated metrics so the dashboard updates
    immediately without a separate refetch.
    """
    result = await admin_service.dispatch_to_ngo(session, body.return_order_id)
    return NgoDispatchResponse(
        return_order_id=result.return_order_id,
        deducted_value=result.deducted_value,
        metrics=_metrics_response(result.metrics),
    )
