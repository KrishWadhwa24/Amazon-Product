"""MetricSnapshot entity (Requirements 13, 16).

Stores admin KPI values: Cache Storage Capacity (used/total), Reverse Logistics
Saved, Carbon Offset Index, and NGO CSR Credits. Recalculated on dispatch
(Requirement 16.2).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Float, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"
    __table_args__ = (
        CheckConstraint("cache_total >= 1", name="cache_total_min_one"),
        CheckConstraint(
            "cache_used >= 0 AND cache_used <= cache_total",
            name="cache_used_within_total",
        ),
        CheckConstraint(
            "reverse_logistics_saved >= 0", name="reverse_logistics_saved_nonneg"
        ),
        CheckConstraint(
            "carbon_offset_index_kg >= 0", name="carbon_offset_index_nonneg"
        ),
        CheckConstraint("ngo_csr_credits >= 0", name="ngo_csr_credits_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cache_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_total: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    reverse_logistics_saved: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    carbon_offset_index_kg: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    ngo_csr_credits: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<MetricSnapshot id={self.id} cache_used={self.cache_used}/"
            f"{self.cache_total}>"
        )
