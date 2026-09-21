"""A research note reaches a visitor only after its verification completed."""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.routers.research_notes import note_for_reader
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
