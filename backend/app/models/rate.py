from datetime import date, datetime

from sqlalchemy import Date, DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Rate(Base):
    """A published rate series value by date (FRED DTB3 for the IV solver), stored the day it is fetched."""
    __tablename__ = "rates"

    series: Mapped[str] = mapped_column(String(20), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False)      # as published, percent
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
