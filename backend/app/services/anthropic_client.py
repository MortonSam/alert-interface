"""Anthropic Claude client for generating and verifying research notes."""

from __future__ import annotations

from anthropic import AsyncAnthropic

from app.config import settings

GENERATION_MODEL   = "claude-sonnet-4-6"
VERIFICATION_MODEL = "claude-opus-4-6"
DRAFT_MODEL        = "claude-fable-5"


def _extract_text(msg) -> str:
    """Extract text content from a response, skipping any thinking blocks."""
    for block in msg.content:
        if block.type == "text":
            return block.text
    raise ValueError("No text block in model response")


def _scrub_em_dashes(text: str) -> str:
    """Replace em dashes with commas (house style)."""
    return text.replace("\u2014", ",")


class AnthropicClient:
    def __init__(self) -> None:
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def generate_research_note(self, prompt: str) -> dict:
        """Generate a research note (structured JSON output).

        Returns:
            {"content": str, "model_used": str, "input_tokens": int, "output_tokens": int}
        """
        msg = await self._client.messages.create(
            model=GENERATION_MODEL,
            max_tokens=2500,
            messages=[{"role": "user", "content": prompt}],
        )
        return {
            "content":       msg.content[0].text,
            "model_used":    GENERATION_MODEL,
            "input_tokens":  msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
        }

    async def generate_options_read(self, prompt: str) -> dict:
        """Generate a short (2–4 sentence) interpretive options setup read.

        Uses Sonnet; max_tokens is tight because the output is prose-only,
        60–100 words. All numbers are injected by the caller — the model only narrates.
        """
        msg = await self._client.messages.create(
            model=GENERATION_MODEL,
            max_tokens=350,
            messages=[{"role": "user", "content": prompt}],
        )
        return {
            "content":       msg.content[0].text.strip(),
            "model_used":    GENERATION_MODEL,
            "input_tokens":  msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
        }

    async def generate_explain(self, prompt: str) -> dict:
        """Generate a 2–3 sentence contextual metric explanation.

        Uses Sonnet; tight max_tokens for short prose output.
        All numbers are injected by the caller — the model only narrates.
        """
        msg = await self._client.messages.create(
            model=GENERATION_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return {
            "content":       msg.content[0].text.strip(),
            "model_used":    GENERATION_MODEL,
            "input_tokens":  msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
        }

    async def generate_thesis_draft(self, prompt: str) -> dict:
        """Generate a data-grounded thesis draft (JSON output).

        Strict JSON output: suggested_target, suggested_strike, strategy, reasoning, realism_flag.
        All numbers must trace to facts injected by the caller — the model only synthesizes.

        Uses DRAFT_MODEL (Fable 5) with high max_tokens to accommodate adaptive
        thinking budget.  The helper _extract_text skips any thinking blocks in
        the response, and _scrub_em_dashes enforces house style.
        """
        msg = await self._client.messages.create(
            model=DRAFT_MODEL,
            max_tokens=16_000,
            messages=[{"role": "user", "content": prompt}],
        )
        return {
            "content":       _scrub_em_dashes(_extract_text(msg).strip()),
            "model_used":    DRAFT_MODEL,
            "input_tokens":  msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
        }

    async def generate_thesis_draft_alternative(self, prompt: str) -> dict:
        """Generate a budget-constrained alternative trade (JSON output).

        Uses DRAFT_MODEL (Fable 5) with high max_tokens to accommodate adaptive
        thinking budget.  _extract_text skips thinking blocks; _scrub_em_dashes
        enforces house style.
        """
        msg = await self._client.messages.create(
            model=DRAFT_MODEL,
            max_tokens=16_000,
            messages=[{"role": "user", "content": prompt}],
        )
        return {
            "content":       _scrub_em_dashes(_extract_text(msg).strip()),
            "model_used":    DRAFT_MODEL,
            "input_tokens":  msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
        }

    async def verify_research_note(self, prompt: str) -> dict:
        """Verify a research note. Uses Opus for higher accuracy.

        Returns:
            {"content": str, "model_used": str, "input_tokens": int, "output_tokens": int}
        """
        msg = await self._client.messages.create(
            model=VERIFICATION_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return {
            "content":       msg.content[0].text,
            "model_used":    VERIFICATION_MODEL,
            "input_tokens":  msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
        }
