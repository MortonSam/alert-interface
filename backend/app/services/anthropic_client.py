"""Anthropic Claude client for generating and verifying research notes."""

from __future__ import annotations

from anthropic import AsyncAnthropic

from app.config import settings

GENERATION_MODEL   = "claude-sonnet-4-6"
VERIFICATION_MODEL = "claude-opus-4-6"
CLASSIFIER_MODEL   = "claude-haiku-4-5-20251001"    # Ask Ivy's question classifier: one small call per question
DRAFT_MODEL        = "claude-fable-5"


def _extract_text(msg) -> str:
    """Extract text content from a response, skipping any thinking blocks."""
    for block in msg.content:
        if block.type == "text":
            return block.text
    raise ValueError("No text block in model response")


def _scrub_dashes(text: str) -> str:
    """Replace em/en dashes with commas, preserving clean spacing."""
    # Spaced dashes first (avoid " , " artifacts)
    text = text.replace(" \u2014 ", ", ").replace(" \u2013 ", ", ")
    # Remaining un-spaced dashes
    text = text.replace("\u2014", ", ").replace("\u2013", ", ")
    # Collapse any double spaces
    while "  " in text:
        text = text.replace("  ", " ")
    return text


class AnthropicClient:
    def __init__(self, timeout: float | None = None, max_retries: int | None = None) -> None:
        """`timeout` (seconds per attempt) and `max_retries` bound a caller that must answer a visitor (Ask Ivy); left out, the SDK's
        defaults apply (ten minutes, two retries), which the nightly's long generations need."""
        kwargs = {}
        if timeout is not None:
            kwargs["timeout"] = timeout
        if max_retries is not None:
            kwargs["max_retries"] = max_retries
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key, **kwargs)

    async def _create(self, method: str, **kwargs):
        """Every call: a failure is recorded with its feature (services/ai_health) before it propagates to the caller."""
        try:
            return await self._client.messages.create(**kwargs)
        except Exception as exc:
            from app.services.ai_health import record_failure
            await record_failure(method, exc)
            raise

    async def generate_research_note(self, prompt: str) -> dict:
        """Generate a research note (structured JSON output).

        Returns:
            {"content": str, "model_used": str, "input_tokens": int, "output_tokens": int}
        """
        msg = await self._create("generate_research_note", 
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
        msg = await self._create("generate_options_read", 
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
        msg = await self._create("generate_explain", 
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
        msg = await self._create("generate_thesis_draft", 
            model=DRAFT_MODEL,
            max_tokens=16_000,
            messages=[{"role": "user", "content": prompt}],
        )
        return {
            "content":       _scrub_dashes(_extract_text(msg).strip()),
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
        msg = await self._create("generate_thesis_draft_alternative", 
            model=DRAFT_MODEL,
            max_tokens=16_000,
            messages=[{"role": "user", "content": prompt}],
        )
        return {
            "content":       _scrub_dashes(_extract_text(msg).strip()),
            "model_used":    DRAFT_MODEL,
            "input_tokens":  msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
        }

    async def read_release_eps(self, prompt: str) -> dict:
        """The second reader of an earnings release (services/release_reader): Sonnet returns JSON with the quarter's GAAP diluted
        EPS and the verbatim quote it came from; the caller verifies the quote and stores only on agreement with the pattern parser."""
        msg = await self._create("read_release_eps", 
            model=GENERATION_MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        return {
            "content":       _extract_text(msg).strip(),
            "model_used":    GENERATION_MODEL,
            "input_tokens":  msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
        }

    async def read_report_date(self, prompt: str) -> dict:
        """The second reader of a company's results-date sentence (services/report_date_reader): Sonnet returns JSON with the
        date, the timing and the verbatim sentence; the caller verifies the sentence and confirms only on agreement with the
        pattern reader."""
        msg = await self._create("read_report_date",
            model=GENERATION_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return {
            "content":       _extract_text(msg).strip(),
            "model_used":    GENERATION_MODEL,
            "input_tokens":  msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
        }

    async def generate_answer(self, prompt: str, max_tokens: int = 400) -> dict:
        """Ask Ivy (services/ask_ivy): a short answer written from a fact pack. Sonnet; the caller forbids any typed number
        and inserts every value itself, so the output is prose with placeholders only."""
        msg = await self._create("generate_answer", 
            model=GENERATION_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return {
            "content":       _extract_text(msg).strip(),
            "model_used":    GENERATION_MODEL,
            "input_tokens":  msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
        }

    async def classify_question(self, prompt: str) -> dict:
        """Ask Ivy's classifier (services/ask_ivy.classify_question): the kind of question, as JSON, from the small model."""
        msg = await self._create("classify_question",
            model=CLASSIFIER_MODEL,
            max_tokens=40,
            messages=[{"role": "user", "content": prompt}],
        )
        return {
            "content":       _extract_text(msg).strip(),
            "model_used":    CLASSIFIER_MODEL,
            "input_tokens":  msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
        }

    async def verify_research_note(self, prompt: str) -> dict:
        """Verify a research note. Uses Opus for higher accuracy.

        Returns:
            {"content": str, "model_used": str, "input_tokens": int, "output_tokens": int}
        """
        msg = await self._create("verify_research_note", 
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
