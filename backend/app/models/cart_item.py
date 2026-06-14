"""CartItem entity.

Backs cart contents and the demand-signal recording fired when a buyer adds a
product to the cart (Requirement 4.1).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.resale_listing import ResaleListing
    from app.models.user import User


class CartItem(Base):
    __tablename__ = "cart_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    # Set when the line is an open-box resale purchase rather than a new catalog
    # item. Null for ordinary catalog adds.
    resale_listing_id: Mapped[int | None] = mapped_column(
        ForeignKey("resale_listings.id", ondelete="SET NULL"), nullable=True
    )
    # The price charged for this line. For catalog items this mirrors the
    # product price; for resale items it is the discounted resale price.
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships (ERD).
    user: Mapped["User"] = relationship(back_populates="cart_items")
    product: Mapped["Product"] = relationship(back_populates="cart_items")
    resale_listing: Mapped["ResaleListing | None"] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<CartItem id={self.id} user_id={self.user_id} product_id={self.product_id}>"
