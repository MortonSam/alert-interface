"""Anthropic Claude client for generating research notes."""

from __future__ import annotations

from anthropic import AsyncAnthropic

from app.config import settings

MODEL = "claude-sonnet-4-6"


class AnthropicClient:
    def __init__(self) -> None:
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def generate_research_note(self, prompt: str) -> dict:
        """Call Claude and return content + token counts.

        Returns:
            {"content": str, "model_used": str, "input_tokens": int, "output_tokens": int}
        """
        msg = await self._client.messages.create(
            model=MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return {
            "content":       msg.content[0].text,
            "model_used":    MODEL,
            "input_tokens":  msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
        }
