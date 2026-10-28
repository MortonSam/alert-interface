"""No visitor ever sees a raw error (Sam, 2026-10-27, BNY: "Generation failed 'NoneType' object has no attribute 'upper'"): a failure
answers with its feature's plain sentence (services/user_errors) and the real error goes to the digest."""
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.services import user_errors
from app.services.research_note_service import _serialize_structured_note

APP = Path(__file__).resolve().parent.parent / "app"
# what Python's exception text looks like when it leaks: a type name, a traceback, a repr of None
EXCEPTION_TEXT = re.compile(r"Traceback|NoneType|object has no attribute|Error\(|Exception\(|KeyError|TypeError|ValueError|"
                            r"AttributeError|RuntimeError|line \d+, in ")


def test_a_withheld_outcome_never_breaks_a_note():
    # LICENSED_ESTIMATES off keeps latest_outcome as None (licensed_estimates.strip_fields): the cause of BNY's failure
    note = {"bottom_line": "x", "what_they_do": "y", "highlights": [], "watch": [], "risks": [],
            "stats": {"latest_quarter_date": "2026-10-16", "latest_outcome": None}}
    text = _serialize_structured_note(note, SimpleNamespace(symbol="BNY", name="The Bank of New York Mellon Corporation"))
    assert "*Most recent quarter: 2026-10-16*" in text
    assert "(BEAT)" in _serialize_structured_note({**note, "stats": {**note["stats"], "latest_outcome": "beat"}}, SimpleNamespace(symbol="BNY", name="x"))


def test_a_failed_note_reads_plain_to_every_reader():
    from app.routers.research_notes import _note_for_reader
    now = datetime(2026, 10, 27, tzinfo=timezone.utc)
    note = SimpleNamespace(id=uuid.uuid4(), ticker_id=uuid.uuid4(), generated_at=now, source_filings=[], content="", model_used="pending",
                           input_tokens=0, output_tokens=0, structured_content=None, verification=None, verified_at=None,
                           verification_model=None, status="failed", error="'NoneType' object has no attribute 'upper'",
                           created_at=now, updated_at=now)
    for admin in (False, True):
        read = _note_for_reader(note, admin=admin)
        assert read.error == "Ivy couldn't write this note right now. Try again in a few minutes."
        assert not EXCEPTION_TEXT.search(read.error)


@pytest.mark.asyncio
async def test_an_unhandled_error_answers_with_the_plain_sentence(monkeypatch):
    from app.main import app
    recorded = []
    async def record(feature, exc, symbol=None):
        recorded.append((feature, str(exc), symbol))
    monkeypatch.setattr(user_errors, "record", record)

    async def boom():
        raise AttributeError("'NoneType' object has no attribute 'upper'")
    app.add_api_route("/api/v1/__test_boom", boom)
    try:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t") as c:
            r = await c.get("/api/v1/__test_boom")
    finally:
        app.router.routes = [rt for rt in app.router.routes if getattr(rt, "path", "") != "/api/v1/__test_boom"]
    assert r.status_code == 500 and r.json() == {"detail": user_errors.plain("unexpected")}
    assert not EXCEPTION_TEXT.search(r.text)
    assert recorded == [("unexpected", "'NoneType' object has no attribute 'upper'", "/api/v1/__test_boom")]   # the digest has it


def test_no_route_puts_exception_text_in_a_response():
    """Static: no HTTPException detail and no response field is built from a caught exception."""
    bad = []
    for path in list((APP / "routers").glob("*.py")) + [APP / "services" / "research_note_service.py"]:
        src = path.read_text()
        for m in re.finditer(r"HTTPException\((?:[^()]|\([^()]*\))*\)", src, re.S):
            if re.search(r"\bexc\b|redact\(|str\(e\)|\{e\b", m.group(0)):
                bad.append(f"{path.name}: {m.group(0)[:120]}")
        for m in re.finditer(r"\"(?:note|error|detail|reason|message)\":\s*(?:redact\(|str\(exc|f\"[^\"]*\{(?:exc|e)\b)", src):
            bad.append(f"{path.name}: {m.group(0)[:120]}")
    assert bad == [], bad


def test_every_plain_sentence_is_plain():
    for feature, sentence in user_errors.PLAIN.items():
        assert sentence.endswith("Try again in a few minutes.") and not EXCEPTION_TEXT.search(sentence), feature
    assert user_errors.plain("research_note") == "Ivy couldn't write this note right now. Try again in a few minutes."
    assert user_errors.plain("no-such-feature") == user_errors.PLAIN["unexpected"]
    assert user_errors.digest_lines('[{"feature": "research_note", "symbol": "BNY", "error": "boom"}]') == ["research_note BNY: boom"]


def test_the_note_check_runs_in_the_gate_and_the_nightly():
    from datetime import date
    from app.scripts import note_smoke, refresh
    assert ("Research note check", ["python", "-m", "app.scripts.note_smoke", "--rotate=3"]) in refresh.STEPS
    assert note_smoke.NOTE_SMOKE_GATE == ("BNY", "NVDA", "O", "PTC", "VYLR")
    syms = [f"S{i:03d}" for i in range(503)]
    days = [note_smoke.rotation(syms, 3, date(2026, 10, 28) + __import__("datetime").timedelta(days=d)) for d in range(168)]
    assert all(len(d) == 3 for d in days) and len({s for d in days for s in d}) == 503       # every stock in turn
    # the gate's step is held by scripts/test_push_window.py (host tests): "note check" with the five symbols


def test_the_nightly_writes_missing_notes_first_then_failed_then_reported_since():
    from app.scripts import generate_notes as G, refresh
    rows = [("AAA", "complete", False), ("BBB", None, False), ("CCC", "failed", False), ("DDD", "complete", True), ("EEE", None, False),
            ("FFF", "verification_failed", False)]
    assert G.queue(rows, 170) == ["BBB", "EEE", "CCC", "FFF", "DDD"]          # AAA is current
    assert G.queue(rows, 2) == ["BBB", "EEE"]
    assert G.MAX_PER_NIGHT == 170 and G.RESERVE_USD > 0
    assert ("Research notes (nightly)", ["python", "-m", "app.scripts.generate_notes"]) in refresh.STEPS
    assert refresh.STEP_TIMEOUTS["Research notes (nightly)"] == 3600


@pytest.mark.asyncio
async def test_withheld_news_says_withheld_and_a_failed_source_never_says_no_news(monkeypatch):
    # Sam (2026-10-27): BNY's page said "No recent news in the last 48 hours" while company news was withheld
    from app.main import app
    from app.routers import tickers as T
    from app.services import personal_use
    monkeypatch.setattr(personal_use, "shown", lambda *a, **k: False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/tickers/BNY/news")
        assert r.json() == {"items": [], "state": "withheld"}
        monkeypatch.setattr(personal_use, "shown", lambda *a, **k: True)
        monkeypatch.setattr(T.news_cache, "get", lambda k: None)

        async def down(*a, **k):
            raise RuntimeError("finnhub 503")
        monkeypatch.setattr(T.FinnhubClient, "get_company_news", down)
        recorded = []
        async def record(feature, exc, symbol=None):
            recorded.append(feature)
        monkeypatch.setattr(user_errors, "record", record)
        r = await c.get("/api/v1/tickers/BNY/news")
        assert r.json() == {"items": [], "state": "unavailable"} and recorded == ["data"]


def test_the_verifier_reply_survives_the_notes_own_quotation_marks():
    # AVY and CARR (2026-10-28): "verification failed: Expecting ',' delimiter"; the claim quoted the filing's "quoted" words unescaped
    from app.services.verification_verdicts import parse_claims
    bad = ('{"claims": [{"claim": "Management calls the quarter "a record" for labels", "verdict": "supported", '
           '"reason": "The 10-Q says "record quarter" in the MD&A."}, {"claim": "Sales rose 4%", "verdict": "unsupported", '
           '"reason": "No figure."}]}')
    rows = parse_claims(bad)
    assert [(r["claim"], r["verdict"]) for r in rows] == [('Management calls the quarter "a record" for labels', "supported"), ("Sales rose 4%", "unsupported")]
    assert rows[0]["reason"] == 'The 10-Q says "record quarter" in the MD&A.'
    assert parse_claims('```json\n{"claims": [{"claim": "x", "verdict": "contradicted", "reason": "y"}]}\n```')[0]["verdict"] == "contradicted"
    with pytest.raises(ValueError):
        parse_claims("I could not verify this note.")
