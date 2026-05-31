"""Anthropic Claude client for generating and verifying research notes."""

from __future__ import annotations

from anthropic import AsyncAnthropic

from app.config import settings

GENERATION_MODEL  = "claude-sonnet-4-6"
VERIFICATION_MODEL = "claude-opus-4-6"


class AnthropicClient:
    def __init__(self) -> None:
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def generate_research_note(self, prompt: str) -> dict:
        """Generate a research note.

        Returns:
            {"content": str, "model_used": str, "input_tokens": int, "output_tokens": int}
        """
        msg = await self._client.messages.create(
            model=GENERATION_MODEL,
            max_tokens=1024,
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

    async def generate_thesis_draft(self, prompt: str) -> dict:
        """Generate a data-grounded thesis draft (JSON output).

        Strict JSON output: suggested_target, suggested_strike, strategy, reasoning, realism_flag.
        All numbers must trace to facts injected by the caller — the model only synthesizes.
        """
        msg = await self._client.messages.create(
            model=GENERATION_MODEL,
            max_tokens=700,
            messages=[{"role": "user", "content": prompt}],
        )
        return {
            "content":       msg.content[0].text.strip(),
            "model_used":    GENERATION_MODEL,
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
