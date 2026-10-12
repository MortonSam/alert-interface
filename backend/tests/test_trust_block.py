"""The trust block of 2026-10-12: one verdict per claim with totals counted from it, a beat or miss only with a reported figure and
counts that state their coverage, the Tape's held ranks and shared session, and the Street Pulse thresholds mirrored."""
import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.main import app
from app.models.enums import EarningsOutcome
from app.scripts.validate_data import CHECKS, ERROR, PASS, check_note_verdicts, check_outcome_requires_actual
from app.services.beat_counts import NO_REPORTED_FIGURE, coverage, served_outcome
from app.services.verification_verdicts import UNSETTLED_REASON, normalize_verification, problems, self_corrected, summary_of
from app.routers.discover import SHARED_SESSION_MIN_ROWS, UnusuallyActiveItem, shared_dominant_session

pytestmark = pytest.mark.xdist_group(name="shared_rows")


# ── 1. verification verdicts ────────────────────────────────────────────────

def test_one_verdict_per_claim_and_the_totals_are_counted_from_the_claims():
    stored = {"claims": [{"claim": "a", "status": "supported", "evidence": "the filing says so"},
                         {"claim": "b", "verdict": "contradicted", "reason": "the stats say 12, the note says 14"},
                         {"claim": "c", "status": "maybe", "evidence": "?"}],
              "summary": {"supported": 22, "unsupported": 9, "contradicted": 0}}       # the model's totals, wrong
    v = normalize_verification(stored)
    assert [c["verdict"] for c in v["claims"]] == ["supported", "contradicted", "unsupported"]
    assert v["claims"][0]["status"] == "supported" and v["claims"][0]["evidence"] == "the filing says so"    # mirrored for older readers
    assert v["summary"] == {"supported": 1, "unsupported": 1, "contradicted": 1}
    assert summary_of(v["claims"]) == v["summary"]
    ps = problems(stored)
    assert any("claim 3: verdict 'maybe'" in p for p in ps) and any("summary says supported 22, the claims count 1" in p for p in ps)
    assert problems({"claims": [{"claim": "a", "verdict": "supported", "reason": "quoted"}], "summary": {"supported": 1, "unsupported": 0, "contradicted": 0}}) == []


def test_a_reason_that_corrects_itself_is_caught():
    assert self_corrected("Initially this looked supported; actually the filing gives 12%, so contradicted.")
    assert self_corrected("Re-evaluating against the stats table, the number is wrong.")
    assert self_corrected("This is unsupported. On reflection it is supported.")
    assert not self_corrected("The 10-Q states revenue of $21.3 billion for the quarter.")
    assert not self_corrected("")
    assert UNSETTLED_REASON.endswith("unsupported.")


@pytest.mark.asyncio
async def test_validate_names_a_stored_note_whose_badges_and_totals_disagree():
    assert check_note_verdicts in CHECKS
    sym = "ZZVRD"
    async with ScriptSessionLocal() as s:
        try:
            await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active) VALUES (gen_random_uuid(), :s, 'Verdict Test', true) ON CONFLICT (symbol) DO NOTHING"), {"s": sym})
            bad = {"claims": [{"claim": "x", "status": "supported", "evidence": "ok"}, {"claim": "y", "status": "unsupported", "evidence": "actually, supported"}],
                   "summary": {"supported": 2, "unsupported": 0, "contradicted": 0}}
            await s.execute(text("""INSERT INTO research_notes (id, ticker_id, generated_at, source_filings, content, model_used, input_tokens, output_tokens, status, verification, created_at, updated_at)
                SELECT gen_random_uuid(), id, now(), '[]'::jsonb, 'note', 'm', 1, 1, 'complete', CAST(:v AS jsonb), now(), now() FROM tickers WHERE symbol = :s"""), {"v": json.dumps(bad), "s": sym})
            await s.commit()
            r = await check_note_verdicts(s)
            assert r.level == ERROR and any(x.startswith(f"{sym}: ") and "corrects itself" in x and "summary says supported 2, the claims count 1" in x for x in r.rows)
            # the API serves the recount, whatever the stored summary says
            from app.config import settings
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                body = (await c.get("/api/v1/research-notes", params={"symbol": sym}, headers={"X-Admin-Token": settings.admin_token} if settings.admin_token else {})).json()
            if "verification" in body and body["verification"]:
                assert body["verification"]["summary"] == {"supported": 1, "unsupported": 1, "contradicted": 0}
                assert body["verification"]["claims"][1]["verdict"] == "unsupported" and body["verification"]["claims"][1]["status"] == "unsupported"
        finally:
            await s.execute(text("DELETE FROM research_notes WHERE ticker_id IN (SELECT id FROM tickers WHERE symbol = :s)"), {"s": sym})
            await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
            await s.commit()


# ── 2. a beat needs a reported figure; counts state their coverage ───────────

class _Row:
    def __init__(self, outcome, actual, estimate):
        self.outcome, self.eps_actual, self.eps_estimate = outcome, actual, estimate


def test_a_beat_or_miss_needs_a_stored_actual_and_counts_state_coverage():
    assert served_outcome(EarningsOutcome.BEAT, None) == NO_REPORTED_FIGURE
    assert served_outcome(EarningsOutcome.MISS, None) == NO_REPORTED_FIGURE
    assert served_outcome(EarningsOutcome.BEAT, 1.02) == "beat" and served_outcome(EarningsOutcome.UNKNOWN, None) == "unknown"
    assert served_outcome("meet", None) == NO_REPORTED_FIGURE and served_outcome(None, None) == "unknown"
    rows = [_Row(EarningsOutcome.BEAT, 1.0, 0.9)] + [_Row(EarningsOutcome.BEAT, None, None)] * 19     # VMRK's shape: 1 quarter with data, 19 without
    cov = coverage(rows)
    assert cov == {"total": 20, "with_data": 1, "without_data": 19, "beats": 1, "misses": 0, "meets": 0}


@pytest.mark.asyncio
async def test_validate_names_a_beat_label_without_an_actual_and_the_api_serves_no_reported_figure():
    assert check_outcome_requires_actual in CHECKS
    sym = "ZZNRF"
    async with ScriptSessionLocal() as s:
        try:
            await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active) VALUES (gen_random_uuid(), :s, 'No Figure Test', true) ON CONFLICT (symbol) DO NOTHING"), {"s": sym})
            await s.execute(text("""INSERT INTO historical_reactions (id, ticker_id, event_type, event_date, pct_change_1d, outcome, computation_version)
                SELECT gen_random_uuid(), id, 'earnings', '2026-07-21', 2.5, 'beat', 3 FROM tickers WHERE symbol = :s"""), {"s": sym})
            await s.commit()
            r = await check_outcome_requires_actual(s)
            assert r.level == ERROR and f"{sym} 2026-07-21: beat" in r.rows
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                rows = (await c.get("/api/v1/reactions", params={"symbol": sym, "event_type": "earnings"})).json()
                items = rows if isinstance(rows, list) else rows.get("items", [])
                assert any(x["outcome"] == NO_REPORTED_FIGURE for x in items), items[:1]
                summary = (await c.get("/api/v1/reactions/summary", params={"symbol": sym})).json()
                assert summary["beat_count"] == 0 and summary["quarters_with_data"] == 0 and summary["quarters_without_data"] == 1
        finally:
            await s.execute(text("DELETE FROM historical_reactions WHERE ticker_id IN (SELECT id FROM tickers WHERE symbol = :s)"), {"s": sym})
            await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
            await s.commit()


# ── 7. the Tape ──────────────────────────────────────────────────────────────

def _item(sym, dominant=None, move=None, hold=None):
    return UnusuallyActiveItem(symbol=sym, name=sym, rv_rank=90.0, rv_20d=0.3, tier="extreme", dominant_date=dominant, dominant_move_pct=move, rank_hold_phrase=hold)


def test_the_tape_names_a_shared_session_once_and_only_when_most_rows_share_it():
    items = [_item("A", "2026-10-05", 20.0), _item("B", "2026-10-05", -8.0), _item("C", "2026-10-05", 5.0), _item("D"), _item("E", "2026-09-30", 4.0)]
    assert shared_dominant_session(items) == {"date": "2026-10-05", "rows": 3, "symbols": ["A", "B", "C"], "up": 2, "down": 1}
    assert shared_dominant_session(items + [_item("F"), _item("G")]) is None          # three of seven is not most
    assert shared_dominant_session([_item("A", "2026-10-05", 1.0), _item("B", "2026-10-05", 1.0)]) is None and SHARED_SESSION_MIN_ROWS == 3
    assert shared_dominant_session([]) is None


# ── 6. Street Pulse thresholds are shared with the page ──────────────────────

def test_street_pulse_thresholds_exist_on_both_sides():
    from app.thresholds import ANALYST_SIGNAL_MIN_MEDIAN_PCT, ANALYST_SIGNAL_MIN_SESSIONS
    from pathlib import Path
    assert ANALYST_SIGNAL_MIN_SESSIONS == 5 and ANALYST_SIGNAL_MIN_MEDIAN_PCT == 1.0
    ts = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "thresholds.ts"
    if not ts.exists():
        pytest.skip("frontend not mounted in this container")       # the frontend lane's tooltips.test.ts checks the mirror from its side
    assert "ANALYST_SIGNAL_MIN_SESSIONS = 5" in ts.read_text() and "ANALYST_SIGNAL_MIN_MEDIAN_PCT = 1.0" in ts.read_text()
