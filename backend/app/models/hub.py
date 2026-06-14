"""Hub entity — dispatch target for reverse-logistics (Requirement 16).

A Hub is a fulfillment/dispatch location that ReturnOrders can be dispatched to
via ``POST /api/admin/dispatch``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Float, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.return_order import ReturnOrder


class Hub(Base):
    __tablename__ = "hubs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)

    return_orders: Mapped[list["ReturnOrder"]] = relationship(back_populates="hub")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Hub id={self.id} name={self.name!r}>"
