"""Block 2 (2026-10-20): W6's reported sentence, W7's average move, W8's FFO wording, Sam's 15% FFO rule and the note strip's EPS."""
from datetime import date

from app.routers.historical_reactions import signed_mean
from app.services import briefing as B
from app.services import ffo as F
from app.services import licensed_estimates as LE
from app.services.eps_year_ago import year_ago_pairs
from app.services.note_valuation import eps_disagreement, served, text_eps


def _ya(quarters, day):
    return LE.YearAgo(year_ago_pairs(quarters)).for_report(day)


def test_w6_with_a_year_ago_figure():
    y = _ya([(date(2025, 7, 27), 1.08), (date(2026, 7, 26), 2.46)], date(2026, 8, 26))
    t, inputs, _ = B.reported_clause(today=date(2026, 8, 28), event_date=date(2026, 8, 26), timing="amc", pct_change_1d=8.7, year_ago=y)
    assert t == "Reported Aug 26, 2026 after the close, with EPS of $2.46, up 127.8% from $1.08 a year ago. The stock moved +8.7% the next session."
    assert not any(LE.mentions_estimates(str(i)) for i in inputs)


def test_w6_with_no_year_ago_figure_and_a_move_still_settling():
    y = _ya([(date(2026, 7, 26), 2.39)], date(2026, 8, 26))
    t, _, _ = B.reported_clause(today=date(2026, 8, 27), event_date=date(2026, 8, 26), timing="amc", bars_through=date(2026, 8, 26), year_ago=y)
    assert t == ("Reported Aug 26, 2026 after the close, with EPS of $2.39, with no figure from the same quarter a year earlier on file. "
                 "The move settles at today's close.")


def test_w6_for_a_derived_ffo_figure_carries_w8s_note_in_the_line_and_the_receipt():
    pairs = [{**p, "measure": F.MEASURE, "note": F.DERIVED_NOTE} for p in year_ago_pairs([(date(2025, 6, 30), 1.63), (date(2026, 6, 30), 2.68)])]
    y = LE.YearAgo(pairs).for_report(date(2026, 7, 29))
    t, inputs, _ = B.reported_clause(today=date(2026, 8, 3), event_date=date(2026, 7, 29), timing="bmo", pct_change_1d=-1.25, year_ago=y)
    assert t == ("Reported Jul 29, 2026 before the open, with FFO per share of $2.68 (calculated from the release's total FFO and diluted shares), "
                 "up 64.4% from $1.63 a year ago. The stock moved -1.2% that session.")
    src = next(i for i in inputs if i["name"] == "FFO per share")["source"]
    assert "checked against the company's SEC filings" in src and src.endswith("(calculated from the release's total FFO and diluted shares)")
    assert "read twice" not in src and "XBRL" not in src


def test_w7_is_the_mean_of_the_signed_moves():
    moves = [6.0, -1.0, -2.0, 1.0]
    assert signed_mean(moves) == 1.0                  # the mean; the median is 0.0 and the mean of absolute moves 2.5
    assert signed_mean([]) is None


def test_ffo_agreed_verbatim_figures_are_shown_within_15_percent_and_held_past_it():
    x = {"ffo_per_share": 1.00, "tags": ["NetIncomeLoss"]}
    assert F.cross_check(1.12, x, agreed_verbatim=True)[0] == "ok"           # 12% apart, agreed: shown
    state, gap, reason = F.cross_check(1.22, x, agreed_verbatim=True)
    assert state == "held" and gap == 22.0 and "over 15%" in reason           # past 15%: held with its reason
    assert F.cross_check(1.06, x)[0] == "held"                                # without agreement the 5% rule is unchanged


TSLA_TEXT = ("## Key Risks\n- **Earnings per share declining year over year** Diluted EPS of $0.32 in Q2 2026 was down 3.0% from $0.33 in Q2 2025, "
             "and trailing four-quarter diluted EPS of $1.08 is down 35.7% compared to the prior four quarters.")


def test_the_note_text_eps_is_the_quarters_and_a_strip_that_disagrees_is_named():
    assert text_eps([TSLA_TEXT]) == 0.32
    assert text_eps(["trailing four-quarter diluted EPS of $1.08"]) is None
    assert text_eps(["earned $1.24 per diluted share"]) == 1.24 and text_eps(["net income of $1.24 billion"]) is None
    strip = lambda v: {"stats": {"eps_sec": v}}
    assert eps_disagreement(strip(0.32), TSLA_TEXT) is None
    assert eps_disagreement(strip(0.33), TSLA_TEXT) == "strip EPS $0.33, text $0.32"


def test_a_served_note_drops_every_vendor_figure_from_the_strip():
    sc, _, _ = served({"stats": {"eps_actual": 0.33, "eps_estimate": 0.54, "eps_beat_pct": -38.9, "revenue_actual": 1e9, "latest_quarter_date": "2026-07-22"}},
                      None, None, False)
    assert sc["stats"] == {"eps_actual": None, "eps_estimate": None, "eps_beat_pct": None, "revenue_actual": None, "latest_quarter_date": "2026-07-22"}


def test_the_overviews_method_names_no_estimate_with_licensed_estimates_off(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "licensed_estimates", False)
    rule = B._reported_rule()
    assert rule == "the reported EPS from SEC filings against the same quarter a year earlier" and not LE.mentions_estimates(rule)
    src = open(B.__file__).read()
    assert "{_reported_rule()}" in src                                  # the rule is built from it, never retyped
