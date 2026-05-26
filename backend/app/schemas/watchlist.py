import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.ticker import TickerRead


class WatchlistBase(BaseModel):
    name: str
    description: str | None = None


class WatchlistCreate(WatchlistBase):
    pass


class WatchlistUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class WatchlistTickerAdd(BaseModel):
    ticker_id: uuid.UUID
    notes: str | None = None


class WatchlistTickerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticker_id: uuid.UUID
    notes: str | None
    added_at: datetime
    ticker: TickerRead


class WatchlistRead(WatchlistBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    items: list[WatchlistTickerRead] = []
