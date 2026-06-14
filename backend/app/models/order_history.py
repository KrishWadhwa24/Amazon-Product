"""OrderHistory entity (Requirement 2.6).

Links a User to a previously purchased Product with a ``purchased_at`` timestamp
that must be earlier than the current time (enforced by the seed and service
layer). The 7-day resale-eligibility rule (Requirement 11.1) is evaluated
against ``purchased_at``.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.resale_listing import ResaleListing
    from app.models.return_order import ReturnOrder
    from app.models.user import User


class OrderHistory(Base):
    __tablename__ = "order_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships (ERD).
    user: Mapped["User"] = relationship(back_populates="order_history")
    product: Mapped["Product"] = relationship(back_populates="order_history")
    return_orders: Mapped[list["ReturnOrder"]] = relationship(
        back_populates="order_history"
    )
    resale_listings: Mapped[list["ResaleListing"]] = relationship(
        back_populates="order_history"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<OrderHistory id={self.id} user_id={self.user_id} product_id={self.product_id}>"
