import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator


class SourceFiling(BaseModel):
    form_type: str
    accession_number: str
    filing_date: str
    url: str


class ResearchNoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticker_id: uuid.UUID
    generated_at: datetime
    source_filings: list[SourceFiling]
    content: str
    model_used: str
    input_tokens: int
    output_tokens: int
    created_at: datetime
    updated_at: datetime


class ResearchNoteGenerateRequest(BaseModel):
    ticker_id: uuid.UUID | None = None
    symbol: str | None = None

    @model_validator(mode="after")
    def require_one(self) -> "ResearchNoteGenerateRequest":
        if self.ticker_id is None and self.symbol is None:
            raise ValueError("Either ticker_id or symbol is required")
        return self
