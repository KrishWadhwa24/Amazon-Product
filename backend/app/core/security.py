"""Signed session-cookie helpers (Requirement 1.4).

The backend binds every user-context request to a logged-in user id via a
signed, HTTP-only session cookie. This module centralizes the cookie *name* and
the sign/verify logic so all consumers agree on the format:

* The auth login flow (task 14.1) calls :func:`sign_session` to mint the cookie
  value and sets it under :data:`SESSION_COOKIE_NAME`; logout clears that cookie.
* The :func:`app.api.deps.get_current_user_id` dependency calls
  :func:`read_session` to resolve the active user id on protected routes.

The token is signed with ``itsdangerous`` using the configured
``SESSION_SECRET`` so it cannot be forged client-side, and is timestamped so a
future task can enforce an expiry by passing ``max_age``. Signing is the only
trust boundary here — the payload is a small JSON object carrying the user id.
"""

from __future__ import annotations

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import get_settings

#: Name of the HTTP-only cookie that carries the signed session token.
SESSION_COOKIE_NAME = "edge_session"

#: Salt namespacing the serializer so the secret is not reused verbatim.
_SESSION_SALT = "amazon-edge-return:session"


def get_session_serializer() -> URLSafeTimedSerializer:
    """Return a serializer bound to the configured session secret.

    Built per call from cached settings so a rotated ``SESSION_SECRET`` is
    picked up without holding a stale serializer.
    """
    return URLSafeTimedSerializer(get_settings().session_secret, salt=_SESSION_SALT)


def sign_session(user_id: int) -> str:
    """Return a signed session token encoding ``user_id``.

    Used by the auth login flow to populate the session cookie value
    (Requirement 1.2). The returned string is URL-safe and tamper-evident.
    """
    return get_session_serializer().dumps({"user_id": user_id})


def read_session(token: str, *, max_age: int | None = None) -> int | None:
    """Resolve the user id from a signed session ``token``.

    Returns the integer user id when the signature is valid (and, if
    ``max_age`` is given, the token has not expired), otherwise ``None`` for a
    missing/forged/expired or malformed token. Callers treat ``None`` as "no
    authenticated session" (Requirement 1.4).
    """
    if not token:
        return None
    try:
        payload = get_session_serializer().loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(payload, dict):
        return None
    user_id = payload.get("user_id")
    # Guard against bools (a subclass of int) and non-integers.
    if isinstance(user_id, int) and not isinstance(user_id, bool):
        return user_id
    return None
