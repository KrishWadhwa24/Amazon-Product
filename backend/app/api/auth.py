"""Auth router — login, logout, and session resolution (Requirement 1).

Implements the auth endpoints from the design's REST API Contract:

* ``POST /api/auth/login`` — verifies email + password against the seeded
  accounts (Requirements 1.2, 1.3), sets the signed HTTP-only session cookie on
  success, and returns ``{user_id, name, role, can_sell}``. A credential
  mismatch raises :class:`LoginFailedError` -> ``401 AUTH_FAILED`` and sets no
  cookie (Requirement 1.3).
* ``POST /api/auth/logout`` — clears the session cookie server-side so no
  subsequent request resolves to that user, returning ``204`` (Requirement 1.6).
* ``GET /api/auth/session`` — resolves the active user from the cookie
  (Requirement 1.4) and returns ``{user_id, name, role, can_sell}``, or
  ``401 NO_SESSION`` when no valid session is present.

The active user id is resolved via :func:`app.api.deps.get_current_user_id`,
the canonical session-resolution seam used by all protected routes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.core.errors import AuthError
from app.core.security import SESSION_COOKIE_NAME, sign_session
from app.db.session import get_session
from app.models.enums import UserRole
from app.models.user import User
from app.services import auth as auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """Request body for ``POST /api/auth/login`` (Requirement 1.2)."""

    email: str
    password: str


class SessionResponse(BaseModel):
    """Identity payload returned by login and session resolution.

    ``can_sell`` reflects whether the user has OrderHistory and may therefore
    act as a Seller (Requirement 1.5).
    """

    user_id: int
    name: str
    role: UserRole
    can_sell: bool


def _set_session_cookie(response: Response, user_id: int) -> None:
    """Set the signed, HTTP-only session cookie for ``user_id`` (Req 1.2, 1.4).

    ``httponly`` keeps the token out of JS; ``samesite='lax'`` permits the
    top-level navigations the demo uses; ``secure=False`` is intentional for
    local HTTP development (a production deploy would set ``secure=True``).
    """
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=sign_session(user_id),
        httponly=True,
        samesite="lax",
        secure=False,
    )


@router.post(
    "/login",
    response_model=SessionResponse,
    summary="Authenticate against a seeded account and establish a session",
)
async def login(
    body: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> SessionResponse:
    """Verify credentials and establish exactly one session (Req 1.2, 1.3).

    On success sets the signed HTTP-only session cookie and returns the user
    identity plus ``can_sell``. A mismatch raises
    :class:`~app.core.errors.LoginFailedError`, rendered as ``401 AUTH_FAILED``
    by the domain-error handler with no cookie set (Requirement 1.3).
    """
    user = await auth_service.verify_credentials(session, body.email, body.password)
    sellable = await auth_service.can_sell(session, user.id)
    _set_session_cookie(response, user.id)
    return SessionResponse(
        user_id=user.id, name=user.name, role=user.role, can_sell=sellable
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Terminate the active session by clearing the cookie",
)
async def logout(response: Response) -> Response:
    """Clear the session cookie so no later request resolves the user (Req 1.6)."""
    response.delete_cookie(key=SESSION_COOKIE_NAME, samesite="lax")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get(
    "/session",
    response_model=SessionResponse,
    summary="Resolve the active user from the session cookie",
)
async def get_session_identity(
    user_id: int | None = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> SessionResponse:
    """Return the active user's identity (Req 1.4) or ``401 NO_SESSION``.

    Resolves the user id from the signed cookie; when absent/forged the
    dependency yields ``None`` and this raises :class:`AuthError`
    (``401 NO_SESSION``). A valid cookie whose user no longer exists is treated
    the same way.
    """
    if user_id is None:
        raise AuthError()

    user = await session.get(User, user_id)
    if user is None:
        raise AuthError()

    sellable = await auth_service.can_sell(session, user.id)
    return SessionResponse(
        user_id=user.id, name=user.name, role=user.role, can_sell=sellable
    )
