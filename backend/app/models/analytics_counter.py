"""AnalyticsCounter entity — a simple named integer counter (Requirement 6.7).

The Matching_Engine must increment an "active-match count" by one each time it
creates a PENDING MatchCandidate (Requirement 6.7); the design refers to this as
``AnalyticsCounter.active_match_count``. Rather than overload the snapshot-style
:class:`~app.models.metric_snapshot.MetricSnapshot` rows (which represent
point-in-time KPI captures), this provides a tiny dedicated key/value counter
table so the running tally has one obvious home.

Each row is one named counter (``name`` is unique) holding a non-negative
integer ``value``. The matching engine bumps the ``active_match`` counter; other
running tallies can reuse the same mechanism without a schema change. The table
is registered on the shared ``Base.metadata`` so it is created automatically by
the seed script and the test harness alongside every other entity.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AnalyticsCounter(Base):
    __tablename__ = "analytics_counters"
    __table_args__ = (
        CheckConstraint("value >= 0", name="value_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Stable counter name (e.g. "active_match"); unique so increments target one row.
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<AnalyticsCounter name={self.name!r} value={self.value}>"
