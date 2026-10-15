"""A served research note: no valuation multiple while PE_ENABLED is off, and no figure the Overview states (services/note_valuation)."""
from app.services.note_valuation import leaks, served
from app.services.verification_verdicts import normalize_verification

NOTE = {
    "highlights": [{"lead": "Revenue grew", "detail": "Revenue rose 12% from a year earlier."},
                   {"lead": "Rich valuation", "detail": "The stock trades at 62x forward earnings, a P/E well above its sector."}],
    "watch": [{"lead": "Robotaxi", "detail": "Any disappointment could compress multiples significantly."}],
    "risks": [{"lead": "Rates", "detail": "Higher rates weigh on REIT values."}],
    "bottom_line": "With a market capitalization of $47.32B, VMRK holds a significant position. Results improved. Its EV/EBITDA is 25x.",
    "stats": {"market_cap": 47_320_000_000, "eps_actual": 0.31},
    "financials": {"pe_ttm": 61.2, "forward_pe": 58.0, "gross_margin": 0.41},
}
VER = {"claims": [{"claim": "Revenue rose 12%", "verdict": "supported", "reason": "10-Q states it"},
                  {"claim": "The P/E is 61", "verdict": "unsupported", "reason": "not in the filing"},
                  {"claim": "Market cap is $47.32B", "verdict": "supported", "reason": "stats"}]}


def test_multiples_are_withheld_while_pe_is_off_and_market_cap_figures_always():
    s, v, c = served(NOTE, VER, "Tesla trades at a P/E of 180. Deliveries rose.", valuation_shown=False)
    assert [p["lead"] for p in s["highlights"]] == ["Revenue grew"] and s["watch"] == [] and len(s["risks"]) == 1
    assert s["bottom_line"] == "Results improved."
    assert s["stats"]["market_cap"] is None and s["stats"]["eps_actual"] == 0.31
    assert s["financials"] == {"gross_margin": 0.41}
    assert [x["claim"] for x in v["claims"]] == ["Revenue rose 12%"]
    assert normalize_verification(v)["summary"] == {"supported": 1, "unsupported": 0, "contradicted": 0}
    assert c == "Deliveries rose."
    assert leaks(s, v, c, False) == []
    assert leaks(NOTE, VER, None, False)                       # the stored note itself would leak


def test_with_pe_on_multiples_stay_and_the_market_cap_still_goes():
    s, v, _ = served(NOTE, VER, None, valuation_shown=True)
    assert len(s["highlights"]) == 2 and s["financials"]["pe_ttm"] == 61.2
    assert s["bottom_line"] == "Results improved. Its EV/EBITDA is 25x."
    assert s["stats"]["market_cap"] is None
    assert [x["claim"] for x in v["claims"]] == ["Revenue rose 12%", "The P/E is 61"]
