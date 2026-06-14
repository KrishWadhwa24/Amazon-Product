"""ReturnOrder entity (Requirements 3, 10).

Represents a returned item entering the 48-hour scanner pool. ``status`` is
constrained to the Return_Lifecycle enum (Requirement 10). ``expires_at`` is
``initiated_at`` + 48h (172,800 s, Requirement 3.1). ``order_history_id`` links
the source purchase; ``reverse_transit_threshold`` is persisted when computed on
the SCANNING -> EXPIRED transition (Requirement 10.9); ``hub_id`` is set on
dispatch.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ReturnStatus

if TYPE_CHECKING:
    from app.models.hub import Hub
    from app.models.match_candidate import MatchCandidate
    from app.models.order_history import OrderHistory
    from app.models.product import Product
    from app.models.user import User


class ReturnOrder(Base):
    __tablename__ = "return_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    seller_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    order_history_id: Mapped[int] = mapped_column(
        ForeignKey("order_history.id", ondelete="RESTRICT"), nullable=False
    )
    # Denormalized ASIN of the returned product (Requirement 3.2).
    asin: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[ReturnStatus] = mapped_column(
        SAEnum(ReturnStatus, native_enum=False, validate_strings=True, length=20),
        nullable=False,
        default=ReturnStatus.SCANNING,
    )
    initiated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hub_id: Mapped[int | None] = mapped_column(
        ForeignKey("hubs.id", ondelete="SET NULL"), nullable=True
    )
    # Computed at SCANNING -> EXPIRED: estimated_reverse_logistics_cost + ₹150.
    reverse_transit_threshold: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    # Relationships (ERD).
    seller: Mapped["User"] = relationship(
        back_populates="return_orders", foreign_keys=[seller_id]
    )
    product: Mapped["Product"] = relationship(back_populates="return_orders")
    order_history: Mapped["OrderHistory"] = relationship(back_populates="return_orders")
    hub: Mapped["Hub | None"] = relationship(back_populates="return_orders")
    match_candidates: Mapped[list["MatchCandidate"]] = relationship(
        back_populates="return_order", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<ReturnOrder id={self.id} asin={self.asin!r} status={self.status}>"
