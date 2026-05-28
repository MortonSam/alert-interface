import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class TickerBase(BaseModel):
    symbol: str = Field(..., max_length=10)
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    exchange: str | None = None
    market_cap: int | None = None
    is_active: bool = True


class TickerCreate(TickerBase):
    pass


class TickerUpdate(BaseModel):
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    exchange: str | None = None
    market_cap: int | None = None
    is_active: bool | None = None


class TickerRead(TickerBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    next_earnings_date: date | None = None
    created_at: datetime
    updated_at: datetime
