"""A mark's dates live in their own fields; as_of is always a timestamp, never a sentence."""
import re
from datetime import datetime
from pathlib import Path

from app.schemas.thesis import MARK_BASES, ThesisMarkRead

THESIS_ROUTER = (Path(__file__).resolve().parents[1] / "app" / "routers" / "thesis.py").read_text()


def _mark_function() -> str:
    start = THESIS_ROUTER.index("async def _compute_option_mark(")
    return THESIS_ROUTER[start:THESIS_ROUTER.index("# ── Shared data pipeline", start)]


def test_schema_has_separate_date_fields():
    for field in ("as_of", "chain_date", "options_as_of", "price_as_of"):
        assert field in ThesisMarkRead.model_fields


def test_as_of_is_never_assigned_prose_or_a_made_up_time():
    body = _mark_function()
    # statements only ("as_of = ..."), not the keyword argument "as_of=as_of,"
    assignments = re.findall(r"^\s*as_of = (\S+)", body, re.M)
    assert assignments == ["datetime.now(tz=timezone.utc).isoformat()"]
    assert "chain as of" not in body.replace("Mark unavailable", "")
    assert "T20:00:00Z" not in body          # the old fabricated settlement timestamp


def test_every_mark_basis_the_function_sets_is_declared():
    used = set(re.findall(r'mark_basis\s*=\s*"([a-z_]+)"', _mark_function()))
    assert used and used <= set(MARK_BASES)


def test_a_mark_round_trips_with_real_dates():
    mark = ThesisMarkRead(
        thesis_id="00000000-0000-0000-0000-000000000001", option_type="call", strike=150, strike2=None,
        current_price=152.3, current_mid1=4.1, current_mid2=None, entry_premium=3.0, entry_premium2=None,
        contracts=1, pnl_dollars=110.0, pnl_pct=36.67, mark_basis="ingested_chain", is_expired=False,
        mark_note=None, as_of="2026-09-21T18:00:00+00:00", chain_date="2026-09-18",
        options_as_of="2026-09-18", price_as_of="2026-09-21T17:59:00+00:00",
    )
    datetime.fromisoformat(mark.as_of)
    datetime.fromisoformat(mark.price_as_of)
    assert mark.chain_date == "2026-09-18"


def test_draft_price_is_dated_by_the_quote_not_the_chain():
    assert '"price_as_of":               price_as_of,' in THESIS_ROUTER
    assert '"price_as_of":               options_as_of' not in THESIS_ROUTER
    assert "Chains refresh during market hours" not in THESIS_ROUTER
