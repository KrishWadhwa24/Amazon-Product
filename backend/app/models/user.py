"""User entity (Requirements 1, 2.3, 2.4).

A User has authentication credentials (``email`` + ``password_hash``), an
advisory ``role``, and geographic coordinates used by the matching engine to
compute buyer-to-seller distance (Requirement 6.3). Seed coordinates: Priya
(12.9781, 77.6389), Rahul (12.9352, 77.6271).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Float, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import UserRole

if TYPE_CHECKING:
    from app.models.cart_item import CartItem
    from app.models.match_candidate import MatchCandidate
    from app.models.notification import Notification
    from app.models.order_history import OrderHistory
    from app.models.resale_listing import ResaleListing
    from app.models.return_order import ReturnOrder


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # email is unique and pairs with password_hash for authentication (Req 1.2).
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, native_enum=False, validate_strings=True, length=16),
        nullable=False,
        default=UserRole.BUYER,
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)

    # Relationships (ERD).
    order_history: Mapped[list["OrderHistory"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    return_orders: Mapped[list["ReturnOrder"]] = relationship(
        back_populates="seller",
        foreign_keys="ReturnOrder.seller_id",
        cascade="all, delete-orphan",
    )
    match_candidates: Mapped[list["MatchCandidate"]] = relationship(
        back_populates="buyer", cascade="all, delete-orphan"
    )
    cart_items: Mapped[list["CartItem"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="buyer", cascade="all, delete-orphan"
    )
    resale_listings: Mapped[list["ResaleListing"]] = relationship(
        back_populates="seller", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<User id={self.id} email={self.email!r} role={self.role}>"
