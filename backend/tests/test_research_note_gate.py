"""A research note reaches a visitor only after its verification completed."""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.routers.research_notes import _note_for_reader as note_for_reader
from app.services.research_note_service import STATUS_VERIFICATION_FAILED, is_verified, verification_failed

NOW = datetime(2026, 9, 21, tzinfo=timezone.utc)
VERIFICATION = {"claims": [], "summary": {"supported": 3, "unsupported": 0, "contradicted": 0}}


def _note(status: str, verification=None):
    return SimpleNamespace(
        id=uuid.uuid4(), ticker_id=uuid.uuid4(), generated_at=NOW, source_filings=[],
        content="Revenue grew 12% on cloud strength.", model_used="claude-sonnet", input_tokens=10, output_tokens=20,
        structured_content={"sections": ["x"]}, verification=verification, verified_at=NOW if verification else None,
        verification_model="claude-opus" if verification else None, status=status, error=None,
        created_at=NOW, updated_at=NOW,
    )


def test_failed_verification_is_a_404_for_visitors():
    note = _note(STATUS_VERIFICATION_FAILED)
    assert verification_failed(note) and not is_verified(note)
    with pytest.raises(HTTPException) as err:
        note_for_reader(note, admin=False)
    assert err.value.status_code == 404


def test_legacy_complete_without_verification_is_treated_as_failed():
    # Before this fix a failed check left status="complete" with verification NULL.
    note = _note("complete", verification=None)
    assert verification_failed(note)
    with pytest.raises(HTTPException):
        note_for_reader(note, admin=False)


def test_admin_sees_a_failed_note_flagged():
    read = note_for_reader(_note(STATUS_VERIFICATION_FAILED), admin=True)
    assert read.verification_failed is True
    assert read.content.startswith("Revenue grew")


@pytest.mark.parametrize("status", ["generating", "verifying"])
def test_unverified_text_is_withheld_from_visitors_while_in_progress(status):
    read = note_for_reader(_note(status), admin=False)
    assert read.status == status
    assert read.content == "" and read.structured_content is None
    assert note_for_reader(_note(status), admin=True).content != ""


def test_verified_note_is_served_to_everyone_unflagged():
    note = _note("complete", VERIFICATION)
    assert is_verified(note) and not verification_failed(note)
    for admin in (False, True):
        read = note_for_reader(note, admin=admin)
        assert read.content.startswith("Revenue grew") and read.verification_failed is False


@pytest.mark.asyncio(loop_scope="session")
async def test_a_note_written_before_its_company_reported_again_is_never_current():
    """MU, 2026-10-08: the home page showed MU's Sep 16 note (most recent quarter reported Jun 24) after MU reported on Sep 30.
    report_since names the newer report; the home route skips such a note and 404s when no note qualifies."""
    from datetime import date, datetime, timezone
    from sqlalchemy import text
    from app.database import ScriptSessionLocal
    from app.services.note_currency import report_since
    sym = "ZZNOTE"
    async with ScriptSessionLocal() as s:
        await s.execute(text("DELETE FROM historical_reactions WHERE ticker_id IN (SELECT id FROM tickers WHERE symbol = :s)"), {"s": sym})
        await s.execute(text("DELETE FROM events WHERE ticker_id IN (SELECT id FROM tickers WHERE symbol = :s)"), {"s": sym})
        await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
        tid = (await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active, created_at, updated_at) VALUES (gen_random_uuid(), :s, 'Note test', true, now(), now()) RETURNING id"), {"s": sym})).scalar()
        await s.execute(text("""INSERT INTO events (id, ticker_id, event_type, event_date, title, source, is_confirmed, created_at, updated_at)
                                VALUES (gen_random_uuid(), :t, 'earnings', '2026-06-24', 'q', 'edgar', true, now(), now()),
                                       (gen_random_uuid(), :t, 'earnings', '2026-09-30', 'q', 'edgar', true, now(), now()),
                                       (gen_random_uuid(), :t, 'earnings', '2026-12-17', 'q', 'finnhub', false, now(), now())"""), {"t": tid})
        await s.commit()
        try:
            sep16 = datetime(2026, 9, 16, 14, tzinfo=timezone.utc)
            assert await report_since(s, tid, sep16, date(2026, 10, 8)) == date(2026, 9, 30)
            assert await report_since(s, tid, datetime(2026, 9, 30, 12, tzinfo=timezone.utc), date(2026, 10, 8)) == date(2026, 9, 30)   # same day: before
            assert await report_since(s, tid, datetime(2026, 10, 2, tzinfo=timezone.utc), date(2026, 10, 8)) is None                     # after: current
            assert await report_since(s, tid, sep16, date(2026, 9, 20)) is None                                                         # before Sep 30 happened
        finally:
            await s.execute(text("DELETE FROM events WHERE ticker_id = :t"), {"t": tid})
            await s.execute(text("DELETE FROM tickers WHERE id = :t"), {"t": tid})
            await s.commit()
    src = (__import__("pathlib").Path(__file__).parent.parent / "app" / "routers" / "research_notes.py").read_text()
    assert "await report_since(db, candidate[0].ticker_id, candidate[0].generated_at) is None" in src
