import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class SourceFiling(BaseModel):
    form_type: str
    accession_number: str
    filing_date: str
    url: str


class VerificationClaim(BaseModel):
    claim: str
    status: Literal["supported", "unsupported", "contradicted"]
    evidence: str


class VerificationSummary(BaseModel):
    supported: int
    unsupported: int
    contradicted: int


class VerificationResult(BaseModel):
    claims: list[VerificationClaim]
    summary: VerificationSummary


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
    verification: VerificationResult | None = None
    verified_at: datetime | None = None
    verification_model: str | None = None
    status: str
    error: str | None = None
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


class ResearchNoteVerifyRequest(BaseModel):
    ticker_id: uuid.UUID | None = None
    symbol: str | None = None

    @model_validator(mode="after")
    def require_one(self) -> "ResearchNoteVerifyRequest":
        if self.ticker_id is None and self.symbol is None:
            raise ValueError("Either ticker_id or symbol is required")
        return self
