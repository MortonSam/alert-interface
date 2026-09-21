import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, SmallInteger, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class IvyTrainLog(Base):
    __tablename__ = "ivy_train_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    n_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    positive_rate: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    holdout_accuracy: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    holdout_n: Mapped[int | None] = mapped_column(Integer, nullable=True)
    computation_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
