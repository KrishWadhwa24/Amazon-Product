"""Auth / Session service (Requirement 1).

Owns the side-effecting parts of authentication against the seeded accounts:

* :func:`verify_credentials` looks up a :class:`User` by email and verifies the
  submitted password against the stored bcrypt ``password_hash`` (Requirements
  1.2, 1.3). On success it returns the User; on any mismatch (unknown email or
  bad password) it raises :class:`LoginFailedError` so no session is
  established (Requirement 1.3).
* :func:`can_sell` reports whether a user may act as a Seller — true iff they
  have at least one :class:`OrderHistory` record (Requirement 1.5).

Password hashing mirrors ``seed.py`` (passlib bcrypt) so seeded credentials
verify unchanged. The pure cookie sign/verify lives in :mod:`app.core.security`;
the router (``app.api.auth``) is the only place that sets/clears the cookie.
"""

from __future__ import annotations

from passlib.context import CryptContext
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import LoginFailedError
from app.models.order_history import OrderHistory
from app.models.user import User

# Same scheme as seed.py so bcrypt hashes produced at seed time verify here.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plaintext: str, password_hash: str) -> bool:
    """Return True when ``plaintext`` matches the stored bcrypt ``password_hash``.

    Wraps passlib's constant-time verify and treats a malformed/empty hash as a
    non-match rather than raising, so credential checks always yield a boolean.
    """
    if not password_hash:
        return False
    try:
        return _pwd_context.verify(plaintext, password_hash)
    except ValueError:
        # Unknown/garbage hash format -> treat as a failed match.
        return False


async def verify_credentials(
    session: AsyncSession, email: str, password: str
) -> User:
    """Resolve the seeded User matching ``email``/``password`` (Req 1.2, 1.3).

    Looks up the account by email (case-insensitive) and verifies the password
    against the stored bcrypt hash. Returns the :class:`User` on success.
    Raises :class:`LoginFailedError` when the email is unknown or the password
    does not match, so the caller establishes no session (Requirement 1.3).
    """
    normalized = (email or "").strip().lower()
    stmt = select(User).where(func.lower(User.email) == normalized)
    user = (await session.execute(stmt)).scalar_one_or_none()

    if user is None or not verify_password(password or "", user.password_hash):
        # Identical error for unknown email and bad password (no user enumeration).
        raise LoginFailedError()

    return user


async def can_sell(session: AsyncSession, user_id: int) -> bool:
    """Return True iff the user has >= 1 OrderHistory record (Requirement 1.5).

    A user may act as a Seller (initiate returns / resale listings) only when
    they have at least one purchase in their history.
    """
    stmt = (
        select(func.count())
        .select_from(OrderHistory)
        .where(OrderHistory.user_id == user_id)
    )
    count = (await session.execute(stmt)).scalar_one()
    return count > 0
