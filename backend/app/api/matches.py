"""Matches router — candidate accept/reject lifecycle (Requirement 9).

Wires ``POST /api/matches/{id}/accept`` and ``POST /api/matches/{id}/reject`` to
:mod:`app.services.matches`. The active user id is resolved from the signed
session cookie (Requirement 1.4) and required (anonymous callers get ``401``).
The service enforces ownership (``403 NOT_AUTHORIZED``, Requirement 9.7) and the
PENDING-only guard (``409 OFFER_UNAVAILABLE``, Requirement 9.6); accept also
advances the ReturnOrder along the local-delivery path and expires sibling
PENDING candidates (Requirements 9.2, 9.5, 9.8). An unknown id yields ``404``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_current_user_id
from app.db.session import get_session
from app.models.enums import MatchStatus
from app.models.match_candidate import MatchCandidate
from app.models.return_order import ReturnOrder
from app.services import matches as matches_service

router = APIRouter(prefix="/api/matches", tags=["matches"])


class MatchActionResponse(BaseModel):
    """Confirmation identifying the candidate and its resulting status."""

    candidate_id: int
    status: MatchStatus


async def _load_candidate(
    session: AsyncSession, match_id: int
) -> MatchCandidate | None:
    """Load a MatchCandidate by id with its ReturnOrder and Product eagerly loaded.

    The ``return_order`` relationship is needed by the accept cascade (advancing
    the lifecycle), and ``return_order.product`` is needed to compute the
    logistics savings (Feature 3 — 10% of product price). Both are eager-loaded
    upfront to guarantee availability in the service layer without a second query.
    """
    stmt = (
        select(MatchCandidate)
        .where(MatchCandidate.id == match_id)
        .options(
            selectinload(MatchCandidate.return_order).selectinload(ReturnOrder.product)
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


@router.post(
    "/{match_id}/accept",
    response_model=MatchActionResponse,
    summary="Accept a local open-box deal (Claim Deal)",
)
async def accept_match(
    match_id: int,
    user_id: int = Depends(require_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> MatchActionResponse:
    """Accept a PENDING MatchCandidate for the active buyer (Requirement 9.2).

    Sets the candidate ACCEPTED, advances its ReturnOrder
    ``SCANNING -> MATCH_FOUND -> BUYER_ACCEPTED -> LOCAL_DELIVERY``
    (Requirement 9.5), and expires sibling PENDING candidates
    (Requirements 9.4, 9.8). Raises ``403 NOT_AUTHORIZED`` when the caller does
    not own the candidate (Requirement 9.7) and ``409 OFFER_UNAVAILABLE`` when
    it is not PENDING (Requirement 9.6); ``404`` for an unknown id.
    """
    candidate = await _load_candidate(session, match_id)
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MatchCandidate {match_id} not found",
        )
    candidate = await matches_service.accept_match(
        session, candidate, user_id=user_id
    )
    return MatchActionResponse(candidate_id=candidate.id, status=candidate.status)


@router.post(
    "/{match_id}/reject",
    response_model=MatchActionResponse,
    summary="Reject a local open-box deal (Keep Original Delivery)",
)
async def reject_match(
    match_id: int,
    user_id: int = Depends(require_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> MatchActionResponse:
    """Reject a PENDING MatchCandidate for the active buyer (Requirement 9.3).

    Sets the candidate REJECTED. Raises ``403 NOT_AUTHORIZED`` when the caller
    does not own the candidate (Requirement 9.7) and ``409 OFFER_UNAVAILABLE``
    when it is not PENDING (Requirement 9.6); ``404`` for an unknown id.
    """
    candidate = await _load_candidate(session, match_id)
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MatchCandidate {match_id} not found",
        )
    candidate = await matches_service.reject_match(
        session, candidate, user_id=user_id
    )
    return MatchActionResponse(candidate_id=candidate.id, status=candidate.status)
