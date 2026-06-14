"""Shared FastAPI dependencies for the transport layer.

Currently exposes session resolution used by protected, user-context routes.

``get_current_user_id`` reads the signed session cookie (Requirement 1.4) and
returns the active user id, or ``None`` when no valid session is present. It is
intentionally permissive (returns ``None`` instead of raising) so individual
endpoints decide how to treat anonymous callers — the return-initiation flow,
for example, rejects ``None`` with an auth error (Requirement 3.7).

NOTE FOR TASK 14.1 (auth finalization): this dependency is the canonical
session-resolution seam. The login endpoint should mint the cookie value with
``app.core.security.sign_session(user_id)`` and set it under
``app.core.security.SESSION_COOKIE_NAME``; logout should delete that cookie.
Once real auth lands, ``get_current_user_id`` already resolves those cookies
unchanged — and a stricter ``require_current_user_id`` is provided here for
routes that must hard-fail on anonymous access.
"""

from __future__ import annotations

from fastapi import Cookie, Depends

from app.core.errors import AuthError
from app.core.security import SESSION_COOKIE_NAME, read_session


def get_current_user_id(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> int | None:
    """Resolve the active user id from the signed session cookie.

    Returns the user id when a valid signed cookie is present, otherwise
    ``None`` (no authenticated session). Endpoints that require a user enforce
    that themselves (see :func:`require_current_user_id`).
    """
    if not session_token:
        return None
    return read_session(session_token)


def require_current_user_id(
    user_id: int | None = Depends(get_current_user_id),
) -> int:
    """Return the active user id or raise :class:`AuthError` when absent.

    Convenience for routes that must reject anonymous callers with ``401``.
    """
    if user_id is None:
        raise AuthError()
    return user_id
