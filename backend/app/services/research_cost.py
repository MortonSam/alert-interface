"""Estimated cost of a research note, from the token counts the note stores.

List prices in USD per million tokens, as published on the Anthropic pricing
page when this table was written (2026-09-28). An estimate, not a bill: it is
labelled as such wherever it is shown, and a model missing from the table
gives None rather than a guess.
"""
from __future__ import annotations

PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {   # model: (input, output)
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-fable-5": (10.0, 50.0),        # DRAFT_MODEL (Build a Trade): $10 in, $50 out per MTok, platform.claude.com pricing page
    "claude-fable-5-1": (10.0, 50.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),   # CLASSIFIER_MODEL (Ask Ivy's question classifier): $1 in, $5 out per MTok
}
PRICES_AS_OF = "2026-10-12"


CACHE_WRITE_MULTIPLIER = 1.25      # a 5-minute cache entry is written at 1.25 times the input price
CACHE_READ_MULTIPLIER = 0.1        # and read at 0.1 times it (the models in the table above)


def estimate_cost_usd(model: str | None, input_tokens: int | None, output_tokens: int | None,
                      cache_write_tokens: int = 0, cache_read_tokens: int = 0) -> float | None:
    """`input_tokens` are the uncached input tokens (the API's usage.input_tokens); prompt-cache writes and reads are priced apart."""
    if not model or model not in PRICES_USD_PER_MTOK or input_tokens is None or output_tokens is None:
        return None
    pin, pout = PRICES_USD_PER_MTOK[model]
    cached = (cache_write_tokens or 0) * pin * CACHE_WRITE_MULTIPLIER + (cache_read_tokens or 0) * pin * CACHE_READ_MULTIPLIER
    return round((input_tokens * pin + output_tokens * pout + cached) / 1_000_000, 4)
