"""Status enumerations for the relational schema.

These mirror the "Status Enumerations" section of the design document and are
the canonical state names used throughout the system. They are defined as
``str`` enums so the values serialize cleanly and can back portable
``CHECK``-constrained ``VARCHAR`` columns (``native_enum=False``) that work on
both PostgreSQL and the in-memory engines used by tests.
"""

from __future__ import annotations

from enum import Enum


class UserRole(str, Enum):
    """Advisory role for a User (Requirements 2.3, 2.4).

    A user may always act as a Seller when they have OrderHistory regardless of
    this value (Requirement 1.5); the role drives default UI affordances only.
    """

    SELLER = "Seller"
    BUYER = "Buyer"


class ReturnStatus(str, Enum):
    """ReturnOrder lifecycle states (Requirement 10).

    MICROWAREHOUSE is the canonical terminal cache-storage state (a.k.a.
    CACHE_STORAGE / the admin display alias CACHED).
    """

    SCANNING = "SCANNING"
    MATCH_FOUND = "MATCH_FOUND"
    BUYER_ACCEPTED = "BUYER_ACCEPTED"
    LOCAL_DELIVERY = "LOCAL_DELIVERY"
    EXPIRED = "EXPIRED"
    FC_TRANSIT = "FC_TRANSIT"
    NGO_ROUTING = "NGO_ROUTING"
    MICROWAREHOUSE = "MICROWAREHOUSE"


class MatchStatus(str, Enum):
    """MatchCandidate lifecycle states (Requirements 6, 9)."""

    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ResaleStatus(str, Enum):
    """ResaleListing lifecycle states (Requirements 11, 12)."""

    ACTIVE = "ACTIVE"
    SOLD = "SOLD"
    REMOVED = "REMOVED"


class ConditionGrade(str, Enum):
    """Accepted resale condition grades (Requirements 11.2, 11.3, 11.4)."""

    LIKE_NEW = "Like New"
    GOOD = "Good"
    FAIR = "Fair"


class NotificationStatus(str, Enum):
    """Delivery state for a match Notification (Requirement 8.6)."""

    PENDING = "PENDING"
    DELIVERED = "DELIVERED"


# Convenience tuples of raw values for building CHECK constraints / Enum cols.
RETURN_STATUS_VALUES = tuple(s.value for s in ReturnStatus)
MATCH_STATUS_VALUES = tuple(s.value for s in MatchStatus)
RESALE_STATUS_VALUES = tuple(s.value for s in ResaleStatus)
CONDITION_GRADE_VALUES = tuple(s.value for s in ConditionGrade)
NOTIFICATION_STATUS_VALUES = tuple(s.value for s in NotificationStatus)
USER_ROLE_VALUES = tuple(s.value for s in UserRole)
