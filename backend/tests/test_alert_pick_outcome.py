"""Let Ivy decide: an outcome that produces no draft comes back named, and costs the visitor nothing.

The v2 engine never returns a draft; before, the route charged the visitor's draft slot for every call and
sent the outcome code in picked_direction, so the page showed nothing. Now the response carries outcome,
outcome_label and note, picked_direction only when the outcome names one, and record_draft runs only when
a draft came back. No draft failure detail carries exception text.
"""
import re
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import app.routers.thesis as thesis
from app.main import app
from app.services.ivy_outcomes import IVY_OUTCOMES, ivy_outcome_label

GATES = {
    "vol_gate": "options pricing 8.5%, history says 5.2%",
    "no_features": "no upcoming earnings or ticker not found for AAPL",
    "momentum_gate": "momentum -1.9% above -10% cutoff",
    "insufficient_history": "insufficient history, 3 events",
    "no_fresh_chain": "no fresh options chain for AAPL",
    "skipped": "",
    "structure_failed": "KeyError('strike')",
}


def _result(outcome, note, direction="bullish", draft=None, existing=False):
    return {"outcome": outcome, "leans": [], "pick_id": None, "picked_direction": direction, "note": note,
            "generated_at": "2026-09-30T12:00:00+00:00", "existing_pick": existing, "draft": draft, "season": 2, "receipt": None}


@pytest.mark.asyncio
async def test_each_no_draft_outcome_is_named_and_not_charged(monkeypatch):
    charged: list[str] = []

    async def fake_record(db, caller, ip, symbol):
        charged.append(symbol)

    async def no_limit(db, caller, ip):
        return None

    monkeypatch.setattr(thesis, "record_draft", fake_record)
    monkeypatch.setattr(thesis, "check_draft_limit", no_limit)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        for outcome, note in GATES.items():
            async def fake_compute(sym, db, source="manual", _o=outcome, _n=note):
                return _result(_o, _n)
            monkeypatch.setattr(thesis, "compute_alert_pick", fake_compute)
            r = await c.post("/api/v1/theses/alert-pick", json={"symbol": "aapl"})
            assert r.status_code == 200, (outcome, r.text)
            body = r.json()
            assert body["outcome"] == outcome and body["outcome_label"] == IVY_OUTCOMES[outcome]["label"]
            assert body["draft"] is None and body["picked_direction"] is None, outcome    # a gate names no direction
            if outcome == "structure_failed":
                assert body["note"] is None and "KeyError" not in r.text            # the exception stays in the log
            else:
                assert body["note"] == (note or None)
        assert charged == [], "an outcome without a draft used no draft slot"

        # a pick with no draft (the v2 engine): named, direction given, still free; the draft call is the charged one
        async def fake_pick(sym, db, source="manual"):
            return _result("picked", None, "bullish")
        monkeypatch.setattr(thesis, "compute_alert_pick", fake_pick)
        body = (await c.post("/api/v1/theses/alert-pick", json={"symbol": "AAPL"})).json()
        assert (body["outcome"], body["outcome_label"], body["picked_direction"]) == ("picked", "Picked", "bullish")
        assert charged == []

        # an existing pick: held, free
        async def fake_existing(sym, db, source="manual"):
            return _result("open_pick_exists", "Existing open pick x since 2026-09-20", "bearish", existing=True)
        monkeypatch.setattr(thesis, "compute_alert_pick", fake_existing)
        body = (await c.post("/api/v1/theses/alert-pick", json={"symbol": "AAPL"})).json()
        assert body["existing_pick"] is True and body["picked_direction"] == "bearish" and body["outcome"] == "open_pick_exists"
        assert charged == []

        # only a draft is charged: the charge sits under the draft check in the route
        src = (Path(__file__).resolve().parents[1] / "app" / "routers" / "thesis.py").read_text()
        route = src[src.index('@router.post("/alert-pick"'):src.index('@router.get("/ivy-rule")')]
        assert route.index('if result["draft"] is not None:') < route.index("await record_draft(")
        assert route.count("await record_draft(") == 1


def test_every_outcome_the_route_can_emit_has_a_label_and_no_failure_detail_carries_the_exception():
    src = (Path(__file__).resolve().parents[1] / "app" / "routers" / "thesis.py").read_text()
    emitted = set(re.findall(r'"outcome":\s*"([a-z_]+)"', src)) | set(re.findall(r'outcome_code = "([a-z_]+)"', src))
    assert emitted and emitted <= set(IVY_OUTCOMES), emitted - set(IVY_OUTCOMES)
    assert ivy_outcome_label("skipped").startswith("Passed") and ivy_outcome_label("nonsense") == IVY_OUTCOMES["error"]["label"]
    assert not re.search(r'detail=f"[^"]*\{exc\}', src), "a visitor would read exception text"
    assert "detail=MARKET_DATA_UNAVAILABLE" in src and "detail=DRAFT_UNAVAILABLE" in src
    for sentence in (thesis.MARKET_DATA_UNAVAILABLE, thesis.DRAFT_UNAVAILABLE):
        assert sentence.endswith(".") and "{" not in sentence and "Error" not in sentence
