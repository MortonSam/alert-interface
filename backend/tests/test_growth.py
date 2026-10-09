"""Revenue and EPS growth (services/growth): readings as first filed and as restated, the derived fourth quarter, two readers must
agree, the release's revenue line, swings in words, holds for corporate actions, and the flag."""
from datetime import date

from app.services import growth as G


def fact(start, end, val, filed, form="10-Q"):
    return {"start": start, "end": end, "val": val, "filed": filed, "form": form}


def test_readings_as_first_filed_and_as_restated_and_a_derived_fourth_quarter():
    entries = [fact("2025-01-01", "2025-03-31", 100, "2025-05-01"), fact("2025-01-01", "2025-03-31", 101, "2026-05-01"),
               fact("2025-04-01", "2025-06-30", 110, "2025-08-01"), fact("2025-07-01", "2025-09-30", 120, "2025-11-01"),
               fact("2025-01-01", "2025-12-31", 460, "2026-02-15", "10-K")]
    q = G.quarter_readings(entries, per_share=False)
    assert q[date(2025, 3, 31)]["as_filed"] == 100 and q[date(2025, 3, 31)]["restated"] == 101
    assert q[date(2025, 12, 31)]["derived"] and q[date(2025, 12, 31)]["as_filed"] == 130 and q[date(2025, 12, 31)]["start"] == date(2025, 10, 1)
    assert G.year_ago(date(2026, 3, 31), {date(2025, 3, 31): {}, date(2025, 6, 30): {}}) == date(2025, 3, 31)


def test_two_readers_must_agree():
    q = {"as_filed": 2.46, "restated": None}
    assert G.confirm("eps", q, 2.46)[0] == 2.46 and G.confirm("eps", q, 2.47)[0] == 2.46     # to the cent
    assert G.confirm("eps", q, 2.48)[0] is None
    assert G.confirm("eps", {"as_filed": 1.54, "restated": None, "derived": True}, 1.53)[0] == 1.53         # a derived Q4: the company's own figure
    assert G.confirm("eps", q, None)[2] == "one reader only: no readable release and no later filing yet"
    assert G.confirm("eps", {"as_filed": 1.92, "restated": 1.92}, None)[1] == "XBRL as filed and as restated a year later"
    rev = {"as_filed": 49_836_000_000.0, "restated": None}
    assert G.confirm("revenue", rev, {"raw": "49.8", "number": 49.8, "scale": "billions"})[0] == rev["as_filed"]
    assert G.confirm("revenue", rev, {"raw": "49,836", "number": 49836, "scale": "millions"})[0] == rev["as_filed"]
    assert G.confirm("revenue", rev, {"raw": "19,568", "number": 19568, "scale": "millions"})[0] is None


def test_the_release_revenue_line_is_the_company_not_a_segment():
    jpm = ("Firmwide Metrics n Reported revenue of $49.8 billion and managed revenue of $50.5 billion. Markets revenue was $11.6 billion, up 20%.")
    assert G.parse_release_revenue(jpm)["raw"] == "49.8"
    assert G.parse_release_revenue("In the CIB, revenue grew 19%. Markets revenue was $11.6 billion, up 20%.") is None
    table = "(in millions) Three Months Ended June 30, 2026 2025 Revenues $ 90,007 $ 76,441 Cost of revenues 28,000 24,000"
    r = G.parse_release_revenue(table)
    assert (r["raw"], r["scale"]) == ("90,007", "millions")
    ford = "(in millions) Second Quarter 2025 2026 Change Total revenues 50,184 48,337 (4) %"
    assert G.parse_release_revenue(ford)["raw"] == "48,337"                       # prior year first: the second column
    assert G.parse_release_revenue("Revenue guidance of $100 billion for the full year") is None
    mu = "Record fiscal 2025 revenue of $37.38 billion. Fourth quarter of fiscal 2025 revenue of $11.32 billion, up 46%."
    assert G.parse_release_revenue(mu)["raw"] == "11.32"                          # the year's figure is skipped; the quarter's stays


def test_a_swing_between_a_loss_and_a_profit_is_words_never_a_percentage():
    assert G.growth_words("eps", 1.30, 0.78) == (66.7, "up 66.7% from a year earlier")
    assert G.growth_words("eps", 0.40, -0.20) == (None, "swung to a profit")
    assert G.growth_words("eps", -0.33, 0.30) == (None, "swung to a loss")
    assert G.growth_words("eps", -0.10, -0.30) == (None, "loss narrowed")
    assert G.growth_words("eps", -0.50, -0.30) == (None, "loss widened")
    assert G.growth_words("revenue", 5.0, 0.0) == (None, "from zero a year earlier")


def test_growth_is_held_for_a_corporate_action_inside_the_year_compared():
    acts = [{"kind": "spin_off", "date": date(2026, 6, 29), "name": "Honeywell Aerospace"}, {"kind": "rename_merge", "date": date(2026, 5, 1), "name": "X"}]
    assert G.hold_for_actions(acts, date(2025, 4, 1), date(2026, 6, 30)) == "Spun off Honeywell Aerospace on 2026-06-29, inside the year compared"
    assert G.hold_for_actions(acts, date(2025, 1, 1), date(2026, 3, 31)) is None             # a rename alone holds nothing
    assert G.revenue_tags("Financials")[0] == "RevenuesNetOfInterestExpense" and G.revenue_tags("Utilities")[0] == "Revenues"
    assert G.revenue_tags(None)[0] == "RevenueFromContractWithCustomerExcludingAssessedTax"


def test_the_flag_defaults_off_and_the_route_reads_it():
    from pathlib import Path
    from app.config import Settings
    assert Settings.model_fields["growth_enabled"].default is False
    src = (Path(__file__).parent.parent / "app" / "routers" / "growth.py").read_text()
    assert "if not (settings.growth_enabled or admin):" in src
    refresh = (Path(__file__).parent.parent / "app" / "scripts" / "refresh.py").read_text()
    assert "compute_growth" not in refresh                                                   # computed locally only until approved
