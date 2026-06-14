"""ResaleListing entity (Requirements 11, 12).

A previously purchased Product offered for resale. ``status`` is constrained to
the resale enum (ACTIVE, SOLD, REMOVED). ``condition_grade`` is constrained to
{"Like New", "Good", "Fair"} (Requirements 11.2-11.4). ``condition_image_url``
is NOT NULL and enforced non-empty (Requirements 11.6, 11.7); the
``0 < resale_price <= product.price`` bound is enforced in the service layer
(Requirement 11.2).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ConditionGrade, ResaleStatus

if TYPE_CHECKING:
    from app.models.order_history import OrderHistory
    from app.models.product import Product
    from app.models.user import User


class ResaleListing(Base):
    __tablename__ = "resale_listings"
    __table_args__ = (
        CheckConstraint("resale_price > 0", name="resale_price_positive"),
        # condition_image_url must be a non-empty string (Requirement 11.7).
        CheckConstraint(
            "length(trim(condition_image_url)) > 0",
            name="condition_image_url_nonempty",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    order_history_id: Mapped[int] = mapped_column(
        ForeignKey("order_history.id", ondelete="RESTRICT"), nullable=False
    )
    seller_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[ResaleStatus] = mapped_column(
        SAEnum(ResaleStatus, native_enum=False, validate_strings=True, length=12),
        nullable=False,
        default=ResaleStatus.ACTIVE,
    )
    condition_grade: Mapped[ConditionGrade] = mapped_column(
        SAEnum(ConditionGrade, native_enum=False, validate_strings=True, length=12),
        nullable=False,
    )
    resale_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    # Mock camera capture of live condition — NOT NULL, non-empty (Req 11.6/11.7).
    condition_image_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    listed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships (ERD).
    product: Mapped["Product"] = relationship(back_populates="resale_listings")
    order_history: Mapped["OrderHistory"] = relationship(back_populates="resale_listings")
    seller: Mapped["User"] = relationship(back_populates="resale_listings")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<ResaleListing id={self.id} product_id={self.product_id} "
            f"status={self.status} grade={self.condition_grade}>"
        )
