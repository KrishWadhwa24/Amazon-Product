"""MatchCandidate entity (Requirements 6, 7, 9).

Links an active ReturnOrder to a Buyer with a computed ``distance_km`` and
``signal_source``, and caches the deal impact (``local_discount``,
``delivery_time_saved_hours``, ``carbon_avoided_kg``).

Duplicate guard (Requirement 6.9): a PARTIAL UNIQUE INDEX on
``(return_order_id, buyer_id) WHERE status = 'PENDING'`` guarantees at most one
PENDING candidate per (buyer, return) pair at the database level, while still
allowing historical EXPIRED/REJECTED rows for the same pair.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import text

from app.db.base import Base
from app.models.enums import MatchStatus

if TYPE_CHECKING:
    from app.models.notification import Notification
    from app.models.return_order import ReturnOrder
    from app.models.user import User


class MatchCandidate(Base):
    __tablename__ = "match_candidates"
    __table_args__ = (
        # Partial unique index enforcing the duplicate-PENDING guard (Req 6.9).
        # Provided for both PostgreSQL (production) and SQLite (tests).
        Index(
            "uq_match_candidate_pending_per_pair",
            "return_order_id",
            "buyer_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
            sqlite_where=text("status = 'PENDING'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    return_order_id: Mapped[int] = mapped_column(
        ForeignKey("return_orders.id", ondelete="CASCADE"), nullable=False
    )
    buyer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[MatchStatus] = mapped_column(
        SAEnum(MatchStatus, native_enum=False, validate_strings=True, length=12),
        nullable=False,
        default=MatchStatus.PENDING,
    )
    distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    # One of: cart, buynow, wishlist, viewed (Requirement 6.5).
    signal_source: Mapped[str] = mapped_column(String(16), nullable=False)
    # Cached deal impact (Requirement 7).
    local_discount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )
    delivery_time_saved_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    carbon_avoided_kg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships (ERD).
    return_order: Mapped["ReturnOrder"] = relationship(back_populates="match_candidates")
    buyer: Mapped["User"] = relationship(back_populates="match_candidates")
    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="match_candidate", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<MatchCandidate id={self.id} return_order_id={self.return_order_id} "
            f"buyer_id={self.buyer_id} status={self.status}>"
        )
