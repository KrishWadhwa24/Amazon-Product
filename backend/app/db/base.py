"""Shared SQLAlchemy declarative base for the relational store.

Task 1.2 owns the async engine and session factory; this module defines only
the declarative ``Base`` so that the ORM models (task 2.1) have a single shared
metadata to register on. It is intentionally engine-agnostic: the same
``Base.metadata`` is used by the async engine wiring, by ``seed.py`` for the
drop/recreate phases (Requirement 2.1), and by the test suite.

If task 1.2 later introduces its own ``Base``, it should import this one rather
than declaring a second, so that all tables live on one metadata object.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# A deterministic naming convention keeps constraint/index names stable across
# drop/recreate cycles (Requirement 2.1) and makes Alembic-style migrations and
# partial-index definitions predictable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model.

    Compatible with the async engine/session created in task 1.2 — declaring
    models against this base only builds metadata and does not bind to an
    engine, so async or sync engines can both create the schema from
    ``Base.metadata``.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
