import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AnalystReactionStats(Base):
    """Precomputed per-ticker aggregate stats for analyst upgrade/downgrade reactions."""
    __tablename__ = "analyst_reaction_stats"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)

    # ── Upgrades ─────────────────────────────────────────────────────────────
    upgrade_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_1d_upgrade: Mapped[float | None] = mapped_column(Numeric(8, 4))
    median_1d_upgrade: Mapped[float | None] = mapped_column(Numeric(8, 4))
    avg_5d_upgrade: Mapped[float | None] = mapped_column(Numeric(8, 4))
    upgrade_5d_continuation_pct: Mapped[float | None] = mapped_column(Numeric(5, 1))
    upgrade_5d_sample: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── Downgrades ───────────────────────────────────────────────────────────
    downgrade_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_1d_downgrade: Mapped[float | None] = mapped_column(Numeric(8, 4))
    median_1d_downgrade: Mapped[float | None] = mapped_column(Numeric(8, 4))
    avg_5d_downgrade: Mapped[float | None] = mapped_column(Numeric(8, 4))
    downgrade_5d_continuation_pct: Mapped[float | None] = mapped_column(Numeric(5, 1))
    downgrade_5d_sample: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("symbol", name="uq_analyst_reaction_stats_symbol"),
    )
