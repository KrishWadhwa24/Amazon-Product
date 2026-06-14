"""Persistence layer: database engine/session and the Redis gateway.

Re-exports the common entry points so callers can do, e.g.::

    from app.db import Base, get_session, get_redis, SignalStorageError
"""

from __future__ import annotations

from app.db.base import Base
from app.db.redis_gateway import (
    RedisGateway,
    SignalStorageError,
    get_gateway,
    get_redis,
    get_redis_client,
)
from app.db.session import (
    dispose_engine,
    get_engine,
    get_session,
    get_sessionmaker,
)

__all__ = [
    "Base",
    "RedisGateway",
    "SignalStorageError",
    "get_gateway",
    "get_redis",
    "get_redis_client",
    "dispose_engine",
    "get_engine",
    "get_session",
    "get_sessionmaker",
]
