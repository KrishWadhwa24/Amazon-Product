"""Product catalog entity (Requirement 2.5).

Database-enforced invariants (Requirement 2.5, design "SQLAlchemy Schema
Notes"):
- ``asin`` is UNIQUE and NOT NULL.
- ``price`` NUMERIC(10,2) with CHECK (price > 0).
- ``rating`` CHECK (rating BETWEEN 0 AND 5).
- ``review_count`` CHECK (review_count >= 0).
- ``image_url`` NOT NULL.
- ``estimated_reverse_logistics_cost`` NUMERIC(10,2) CHECK (>= 0), feeding the
  EXPIRED auto-routing decision (Requirement 10.9).

Image upload support (product image uploads, demo placeholder):
- ``image_url`` remains NOT NULL and always carries the seeded placeholder or
  remote catalog URL, satisfying the Requirement 2.5 non-null constraint. The
  application/frontend layer treats it as *optional*: when it is empty or only a
  placeholder, the UI substitutes a demo/placeholder image. This task only
  defines the schema field — the substitution logic lives in the frontend.
- ``uploaded_image_path`` is a NULLABLE column that holds the local filesystem
  path of an image uploaded later via the catalog/admin flow. ``NULL`` means no
  upload exists yet, so the placeholder/``image_url`` is used. The upload
  endpoint itself is wired in a later catalog/admin task, not here.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Float, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.cart_item import CartItem
    from app.models.order_history import OrderHistory
    from app.models.resale_listing import ResaleListing
    from app.models.return_order import ReturnOrder


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price > 0", name="price_positive"),
        CheckConstraint("rating >= 0 AND rating <= 5", name="rating_range"),
        CheckConstraint("review_count >= 0", name="review_count_nonneg"),
        CheckConstraint(
            "estimated_reverse_logistics_cost >= 0",
            name="reverse_logistics_cost_nonneg",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asin: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    rating: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # NOT NULL per Requirement 2.5; carries the seeded placeholder/remote URL.
    image_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    # Nullable path for a later-uploaded local image (NULL => use placeholder).
    uploaded_image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_reverse_logistics_cost: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )

    # Relationships (ERD).
    order_history: Mapped[list["OrderHistory"]] = relationship(back_populates="product")
    return_orders: Mapped[list["ReturnOrder"]] = relationship(back_populates="product")
    cart_items: Mapped[list["CartItem"]] = relationship(back_populates="product")
    resale_listings: Mapped[list["ResaleListing"]] = relationship(
        back_populates="product"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Product id={self.id} asin={self.asin!r} name={self.name!r}>"
