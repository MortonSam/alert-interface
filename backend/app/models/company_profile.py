"""A company's profile from Intrinio's /companies endpoint, stored by the records build with the date it was fetched.
The Overview's "What it is" sentence reads it; nothing in it is typed by hand."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CompanyProfile(Base):
    __tablename__ = "company_profiles"

    symbol: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    short_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sector: Mapped[str | None] = mapped_column(Text, nullable=True)
    industry_category: Mapped[str | None] = mapped_column(Text, nullable=True)
    industry_group: Mapped[str | None] = mapped_column(Text, nullable=True)
    employees: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exchange: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_filing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="intrinio")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
