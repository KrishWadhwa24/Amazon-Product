"""SQLAlchemy ORM models for the relational store.

Importing this package registers every entity on the shared ``Base.metadata``
(defined in ``app.db.base``) so the seed script and engine wiring can create the
full schema from a single metadata object. Models mirror the design ERD.
"""

from __future__ import annotations

from app.db.base import Base
from app.models.analytics_counter import AnalyticsCounter
from app.models.cart_item import CartItem
from app.models.enums import (
    ConditionGrade,
    MatchStatus,
    NotificationStatus,
    ResaleStatus,
    ReturnStatus,
    UserRole,
)
from app.models.hub import Hub
from app.models.match_candidate import MatchCandidate
from app.models.metric_snapshot import MetricSnapshot
from app.models.notification import Notification
from app.models.order_history import OrderHistory
from app.models.product import Product
from app.models.resale_listing import ResaleListing
from app.models.return_order import ReturnOrder
from app.models.user import User

__all__ = [
    "Base",
    # Entities
    "User",
    "Product",
    "OrderHistory",
    "ReturnOrder",
    "MatchCandidate",
    "ResaleListing",
    "CartItem",
    "Notification",
    "MetricSnapshot",
    "Hub",
    "AnalyticsCounter",
    # Enums
    "UserRole",
    "ReturnStatus",
    "MatchStatus",
    "ResaleStatus",
    "ConditionGrade",
    "NotificationStatus",
]
