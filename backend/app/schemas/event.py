import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import DataSource, EventType


class EventBase(BaseModel):
    ticker_id: uuid.UUID | None = None
    event_type: EventType
    event_date: date
    title: str
    description: str | None = None
    source: DataSource = DataSource.MANUAL
    source_url: str | None = None
    is_confirmed: bool = False
    metadata_: dict = {}


class EventCreate(EventBase):
    pass


class EventUpdate(BaseModel):
    event_type: EventType | None = None
    event_date: date | None = None
    title: str | None = None
    description: str | None = None
    source: DataSource | None = None
    source_url: str | None = None
    is_confirmed: bool | None = None
    metadata_: dict | None = None


class EventRead(EventBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
