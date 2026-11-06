"""Ivy's stock walkthrough (services/walkthrough), rebuilt nightly by scripts/build_walkthroughs.

ivy_walkthroughs: one row per symbol. `payload` is what the page shows (seven steps, the summary, the compare row), `sources` the
filing readings it was built from (the 10-K's segments and risk factors, each with its accession, so an unchanged 10-K is never
read twice), `facts_fingerprint` a hash of every displayed fact and `story_fingerprint` a hash of the facts the model's sentences
rest on (a sentence is rewritten only when that changes). `version` is services/walkthrough.WALKTHROUGH_VERSION when it was built.

ivy_compare_stories: Ivy's one verified sentence for a pair of stocks, keyed by both story fingerprints.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class IvyWalkthrough(Base):
    __tablename__ = "ivy_walkthroughs"

    symbol: Mapped[str] = mapped_column(String(10), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)                         # the latest data date the build read (the last stored close)
    facts_fingerprint: Mapped[str] = mapped_column(String(32), nullable=False)
    story_fingerprint: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    sources: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    story: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")   # {sentences by step, verdicts, dropped, model, cost_usd, at}
    steps_shown: Mapped[int] = mapped_column(Integer, nullable=False)                 # steps with trustworthy data (0-7), for validate's coverage check
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class IvyCompareStory(Base):
    __tablename__ = "ivy_compare_stories"

    symbol: Mapped[str] = mapped_column(String(10), primary_key=True)
    other: Mapped[str] = mapped_column(String(10), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(32), nullable=False)
    sentence: Mapped[str | None] = mapped_column(Text, nullable=True)                 # None when the verifier dropped every draft
    verdicts: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
