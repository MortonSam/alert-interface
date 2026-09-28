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
}
PRICES_AS_OF = "2026-09-28"


def estimate_cost_usd(model: str | None, input_tokens: int | None, output_tokens: int | None) -> float | None:
    if not model or model not in PRICES_USD_PER_MTOK or input_tokens is None or output_tokens is None:
        return None
    pin, pout = PRICES_USD_PER_MTOK[model]
    return round((input_tokens * pin + output_tokens * pout) / 1_000_000, 4)
