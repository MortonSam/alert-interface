"""A question never hangs (2026-10-13: a test run stalled inside a model call, which the SDK lets run ten minutes with two retries).
Every Ask Ivy model call is bounded, each stage has a deadline, and a stage past its deadline returns a plain sentence."""
import asyncio
import time

import pytest

from app.services import ask_ivy as A
from app.services.anthropic_client import AnthropicClient

PACK = {"symbol": "TSLA", "name": "Tesla", "facts": [], "context": [], "fingerprint": "f", "active": True}


class NeverAnswers:
    """A model client whose calls never return."""
    async def generate_answer(self, prompt, max_tokens=400):
        await asyncio.sleep(3600)

    async def classify_question(self, prompt):
        await asyncio.sleep(3600)

    async def verify_research_note(self, prompt):
        await asyncio.sleep(3600)


def test_the_ask_client_bounds_every_attempt_and_allows_one_retry():
    c = A.ask_client()
    assert c._client.timeout == A.MODEL_CALL_SECONDS and c._client.max_retries == 1
    default = AnthropicClient()                       # the nightly's long generations keep the SDK's defaults
    assert default._client.max_retries == 2
    assert A.MODEL_CALL_SECONDS * 2 <= A.ANSWER_SECONDS     # one attempt and its retry fit inside the answer's deadline


@pytest.mark.asyncio
async def test_a_model_that_never_answers_gives_the_timeout_sentence_within_the_deadline(monkeypatch):
    monkeypatch.setattr(A, "ANSWER_SECONDS", 0.2)
    monkeypatch.setattr(A, "CLASSIFY_SECONDS", 0.2)
    t = time.monotonic()
    r = await A.answer_within(None, PACK, "is now a good time to buy", client=NeverAnswers(), kind="timing")
    assert time.monotonic() - t < 2
    assert r["verdict"] == "timeout" and r["cost"] == 0.0
    assert r["answer"]["data"] == "Ivy couldn't finish an answer about Tesla in time. Try again in a minute; nothing was charged to your limit."
    assert r["answer"]["inputs"] == []
    with pytest.raises(asyncio.TimeoutError):          # the route and the runner answer as covered_other when the classifier runs out
        await A.classify_question(NeverAnswers(), "is now a good time to buy", "TSLA", "Tesla")


@pytest.mark.asyncio
async def test_a_fact_pack_past_its_deadline_is_none(monkeypatch):
    async def slow_pack(db, symbol, today=None):
        await asyncio.sleep(3600)
    monkeypatch.setattr(A, "fact_pack", slow_pack)
    monkeypatch.setattr(A, "PACK_SECONDS", 0.2)
    t = time.monotonic()
    assert await A.pack_within(None, "TSLA") is None
    assert time.monotonic() - t < 2


def test_the_route_and_the_runner_use_the_bounded_stages():
    from pathlib import Path
    app = Path(__file__).resolve().parents[1] / "app"
    route = (app / "routers" / "tickers.py").read_text().split("async def ask_ivy(")[1].split("\n@router")[0]
    assert "await A.pack_within(db, symbol)" in route and "A.fact_pack(" not in route
    assert "await A.answer_within(db, pack, question, kind=kind)" in route and "A.answer_question(" not in route
    assert "A.classify_question(A.ask_client()" in route
    assert 'if result["verdict"] == "timeout":' in route and route.count("await refund_use(") >= 4      # a timed-out answer is refunded
    runner = (app / "scripts" / "ask_ivy_testset.py").read_text()
    assert "A.pack_within(" in runner and "A.answer_within(" in runner and "A.ask_client()" in runner
