"""Anthropic Claude client for generating and verifying research notes."""

from __future__ import annotations

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


# The one gateway (Sam, 2026-11-16: the console showed $19.91 on the production key from Nov 10 to 14 against $3.11 in the ledger).
# Every model call made by this codebase goes through AnthropicClient._create, and tests/test_ai_gateway.py fails if any module
# imports the SDK, builds its client or calls the API anywhere else. _create, for every attempt of every call:
#   - refuses before sending when the day's cap leaves it no room (a nightly-pool call: ai_spend.check_nightly, as before; a
#     visitor's call: ai_spend.check_visitor, the cap itself) or while a paid reply is still waiting to be written to the ledger
#     (it is written first when the database answers, and the refusal clears on its own);
#   - sends exactly one request: the SDK's own retries are off (max_retries=0), so no attempt is ever sent unseen; the gateway
#     retries itself, re-checking the cap each time;
#   - counts the reply's cost and tokens by day, pool, feature and model (ai_spend.record_call, record_tokens), and an attempt that
#     timed out after it was sent at its ceiling (it may have been processed and billed);
#   - records a failure with its feature (services/ai_health) before raising.
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
RETRY_PAUSE_SECONDS = (1.0, 4.0, 10.0)


class LedgerUnavailable(RuntimeError):
    """Refused before sending: a reply this process could not write to the spend ledger is still waiting to be written."""


LEDGER_WRITE_PAUSES = (0.0, 0.5, 2.0)  # a reply's ledger write is tried three times before it is kept back
_UNRECORDED: list[dict] = []           # replies (or timed-out attempts) paid for but not yet in the ledger, oldest first
_LEDGER_BROKEN: str | None = None      # why, while _UNRECORDED is not empty: every call is refused until they are written


def _retryable(exc: Exception) -> tuple[bool, bool]:
    """Pure: (worth another attempt, may already have been billed). A timeout was sent and may have been processed; a connection
    error, a rate limit or an overloaded server was not."""
    import anthropic
    if isinstance(exc, anthropic.APITimeoutError):
        return True, True
    if isinstance(exc, anthropic.APIConnectionError):
        return True, False
    status = getattr(exc, "status_code", None)
    return (status in RETRYABLE_STATUS), False


async def _write(entry: dict) -> None:
    """One ledger write: the reply's tokens (when known) and its cost, in one transaction (record_call commits)."""
    from app.database import ScriptSessionLocal
    from app.services import ai_spend
    async with ScriptSessionLocal() as s:
        if entry["tokens"] is not None:
            await ai_spend.record_tokens(s, entry["model"], *entry["tokens"])
        await ai_spend.record_call(s, entry["method"], entry["cost"])


async def _alert(title: str, message: str, high: bool) -> None:
    try:
        from app.services import notify
        await notify.notify(title, message, notify.PRIORITY_HIGH if high else notify.PRIORITY_DEFAULT, ("money_with_wings",))
    except Exception:
        pass                               # the alert is a courtesy; the refusal does not depend on it


async def _count(entry: dict) -> None:
    """Write one paid reply to the ledger, retrying (LEDGER_WRITE_PAUSES). When every try fails it is kept in _UNRECORDED, calls are
    refused until it is written (_settle_ledger), and Sam's phone is alerted once per outage. It never fails the call it counts,
    which is already paid for."""
    import asyncio
    global _LEDGER_BROKEN
    err: Exception | None = None
    for pause in LEDGER_WRITE_PAUSES:
        if pause:
            await asyncio.sleep(pause)
        try:
            await _write(entry)
            return
        except Exception as exc:
            err = exc
    from app.services.redact import redact
    _UNRECORDED.append(entry)
    first = _LEDGER_BROKEN is None
    _LEDGER_BROKEN = f"{entry['method']}: {redact(err)[:120]}"
    print(f"[ai-spend] {entry['method']}: ${entry['cost'] or 0:.4f} not recorded; calls refused until it is: {_LEDGER_BROKEN}", flush=True)
    if first:
        await _alert("AI spend ledger could not be written",
                     f"A model reply ({entry['method']}) could not be written to the spend ledger after {len(LEDGER_WRITE_PAUSES)} tries: "
                     f"{_LEDGER_BROKEN}. AI calls are refused until it is written; this clears on its own once the database answers.", True)


async def _settle_ledger() -> None:
    """Before any call while replies are kept back: write them (one try each, oldest first). All written: the refusal clears and
    the phone is told; any still failing: LedgerUnavailable, and the next call tries again."""
    global _LEDGER_BROKEN
    from app.services.redact import redact
    while _UNRECORDED:
        try:
            await _write(_UNRECORDED[0])
        except Exception as exc:
            raise LedgerUnavailable(f"model call refused: {len(_UNRECORDED)} paid repl(ies) not yet in the spend ledger "
                                    f"({_LEDGER_BROKEN}; now {redact(exc)[:80]})") from None
        _UNRECORDED.pop(0)
    if _LEDGER_BROKEN:
        was, _LEDGER_BROKEN = _LEDGER_BROKEN, None
        print(f"[ai-spend] ledger written again; calls allowed (was: {was})", flush=True)
        await _alert("AI spend ledger recovered", f"The kept-back spend was written and AI calls are allowed again (was: {was}).", False)


async def _record_call(method: str, model: str | None, msg) -> None:
    """Count one reply's estimated cost and tokens in services/ai_spend (_count)."""
    from app.services.research_cost import estimate_cost_usd
    u = getattr(msg, "usage", None)
    tin, tout = getattr(u, "input_tokens", None), getattr(u, "output_tokens", None)
    cw, cr = getattr(u, "cache_creation_input_tokens", 0) or 0, getattr(u, "cache_read_input_tokens", 0) or 0
    await _count({"method": method, "model": model, "tokens": (tin or 0, cw, cr, tout or 0),
                  "cost": estimate_cost_usd(model, tin, tout, cw, cr)})


async def _record_unseen(method: str, model: str | None, kwargs: dict) -> None:
    """An attempt that timed out after it was sent: counted at its ceiling (ai_spend.call_ceiling_usd), since it may be billed."""
    from app.services import ai_spend
    await _count({"method": method, "model": model, "tokens": None, "cost": ai_spend.call_ceiling_usd(model, kwargs)})


class AnthropicClient:
    def __init__(self, timeout: float | None = None, max_retries: int | None = None) -> None:
        """`timeout` (seconds per attempt) and `max_retries` (further attempts, made by the gateway, never by the SDK) bound a caller
        that must answer a visitor (Ask Ivy); left out, ten minutes and two retries, which the nightly's long generations need."""
        kwargs = {"max_retries": 0}                  # the SDK never retries on its own: an unseen retry is an unrecorded charge
        if timeout is not None:
            kwargs["timeout"] = timeout
        self._retries = 2 if max_retries is None else max(0, int(max_retries))
        from app.services.prod_key_guard import check_production_key
        check_production_key()          # production's database only with production's environment and key (services/prod_key_guard)
        from anthropic import AsyncAnthropic
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key, **kwargs)

    async def _create(self, method: str, *, probe: bool = False, **kwargs):
        """The gateway (above). `probe` is the nightly key check: it runs while the AI is paused (it is what ends the pause) and
        leaves recording its failure to its caller; the cap and the ledger apply to it as to every call."""
        import asyncio
        from app.database import ScriptSessionLocal
        from app.services import ai_spend
        model = kwargs.get("model")
        attempts = 1 + getattr(self, "_retries", 0)
        for attempt in range(1, attempts + 1):
            if _UNRECORDED:
                await _settle_ledger()
            async with ScriptSessionLocal() as s:
                if ai_spend.pool() == ai_spend.NIGHTLY:
                    await ai_spend.check_nightly(s, model, kwargs, skip_pause=probe)
                else:
                    await ai_spend.check_visitor(s)
            try:
                msg = await self._client.messages.create(**kwargs)
            except Exception as exc:
                again, billed = _retryable(exc)
                if billed:
                    await _record_unseen(method, model, kwargs)
                if again and attempt < attempts:
                    await asyncio.sleep(RETRY_PAUSE_SECONDS[min(attempt, len(RETRY_PAUSE_SECONDS)) - 1])
                    continue
                if not probe:
                    from app.services.ai_health import record_failure
                    await record_failure(method, exc)
                raise
            await _record_call(method, model, msg)
            return msg

    async def key_check(self, model: str) -> dict:
        """The nightly key check (scripts/ai_key_check): a few tokens through the gateway, counted like every other call."""
        msg = await self._create("key_check", probe=True, model=model, max_tokens=5, messages=[{"role": "user", "content": "ping"}])
        return {"model_used": model, "input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens}

    async def generate_research_note(self, prompt: str, retry: str | None = None) -> dict:
        """Generate a research note (structured JSON output). `prompt` is sent as one cached block (5-minute prompt cache), so the
        retry that names the first draft's broken rules (`retry`, a second block after it) reads the prompt from the cache instead of
        paying for it again; the text the model reads is the prompt followed by the retry, as before.

        Returns:
            {"content": str, "model_used": str, "input_tokens": int (uncached), "output_tokens": int,
             "cache_write_tokens": int, "cache_read_tokens": int}
        """
        content = [{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}]
        if retry:
            content.append({"type": "text", "text": retry})
        msg = await self._create("generate_research_note",
            model=GENERATION_MODEL,
            max_tokens=2500,
            messages=[{"role": "user", "content": content}],
        )
        return {
            "content":       msg.content[0].text,
            "model_used":    GENERATION_MODEL,
            "input_tokens":  msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
            "cache_write_tokens": getattr(msg.usage, "cache_creation_input_tokens", 0) or 0,
            "cache_read_tokens":  getattr(msg.usage, "cache_read_input_tokens", 0) or 0,
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

    async def read_release_eps(self, prompt: str, max_tokens: int = 400) -> dict:
        """The second reader of an earnings release (services/release_reader): Sonnet returns JSON with the quarter's GAAP diluted
        EPS and the verbatim quote it came from; the caller verifies the quote and stores only on agreement with the pattern parser."""
        msg = await self._create("read_release_eps", 
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

    async def generate_walkthrough(self, prompt: str, max_tokens: int = 900) -> dict:
        """Ivy's walkthrough (services/walkthrough_story): story and risk sentences as JSON, no figures. Sonnet."""
        msg = await self._create("generate_walkthrough",
            model=GENERATION_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return {"content": _extract_text(msg).strip(), "model_used": GENERATION_MODEL,
                "input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens}

    async def verify_walkthrough(self, prompt: str) -> dict:
        """The walkthrough's verifier: the research-note verifier's model over the fact pack and the filing text."""
        msg = await self._create("verify_walkthrough",
            model=VERIFICATION_MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        return {"content": _extract_text(msg), "model_used": VERIFICATION_MODEL,
                "input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens}

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
