"""Notification entity (Requirement 8.6).

Tracks the PENDING -> delivered state of a match notification surfaced from a
MatchCandidate, honoring the retry/preservation semantics: a notification stays
PENDING until delivered or its ReturnOrder leaves SCANNING (Requirement 8.6).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import NotificationStatus

if TYPE_CHECKING:
    from app.models.match_candidate import MatchCandidate
    from app.models.user import User


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_candidate_id: Mapped[int] = mapped_column(
        ForeignKey("match_candidates.id", ondelete="CASCADE"), nullable=False
    )
    buyer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[NotificationStatus] = mapped_column(
        SAEnum(NotificationStatus, native_enum=False, validate_strings=True, length=12),
        nullable=False,
        default=NotificationStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships (ERD).
    match_candidate: Mapped["MatchCandidate"] = relationship(
        back_populates="notifications"
    )
    buyer: Mapped["User"] = relationship(back_populates="notifications")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<Notification id={self.id} match_candidate_id={self.match_candidate_id} "
            f"status={self.status}>"
        )
