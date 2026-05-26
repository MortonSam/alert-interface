import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models.enums import EventType


class HistoricalReactionBase(BaseModel):
    ticker_id: uuid.UUID
    event_id: uuid.UUID | None = None
    event_type: EventType
    event_date: date
    close_before: Decimal | None = None
    open_after: Decimal | None = None
    close_after: Decimal | None = None
    pct_change_1d: Decimal | None = None
    pct_change_3d: Decimal | None = None
    pct_change_5d: Decimal | None = None
    volume_before: int | None = None
    volume_after: int | None = None
    notes: str | None = None


class HistoricalReactionCreate(HistoricalReactionBase):
    pass


class HistoricalReactionRead(HistoricalReactionBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
