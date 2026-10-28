"""A company-confirmed date never moves on vendor data (Sam, 2026-10-28: the missed-reports step tried to move UHS's company-confirmed
Oct 26 to Yahoo's Oct 27, hit the second row the calendar had made on Oct 27 and rolled back the night's work); one preliminary-8K
rule in every step that reads a release."""
from datetime import date
from pathlib import Path

from app.scripts.catch_up_reports import ensure_plan
from app.services.earnings_calendar import resolve_past, vendor_report_beside_company
from app.services.earnings_release import is_results_release

UHS_COMPANY = (date(2026, 10, 26), True, "confirmed: press release via Finnhub news 2026-10-05: KING OF PRUSSIA, Pa., Oct. 5, 2026")
UHS_YAHOO = (date(2026, 10, 27), True, "reported on Oct 27, 2026 per Yahoo Finance (actual EPS)")
APP = Path(__file__).resolve().parent.parent / "app"


def test_the_missed_reports_step_never_moves_a_company_confirmed_date():
    assert ensure_plan([UHS_COMPANY, UHS_YAHOO], date(2026, 10, 27)) == ("keep", date(2026, 10, 26))   # the night of 2026-10-28
    assert ensure_plan([UHS_COMPANY], date(2026, 10, 27)) == ("keep", date(2026, 10, 26))              # no second row beside it
    assert ensure_plan([UHS_YAHOO], date(2026, 10, 27)) == ("confirm", date(2026, 10, 27))
    estimate = (date(2026, 10, 28), False, "estimated (Finnhub)")
    assert ensure_plan([estimate], date(2026, 10, 27)) == ("move", date(2026, 10, 28))                   # an estimate still moves
    assert ensure_plan([], date(2026, 10, 27)) == ("insert", None)


def test_the_calendar_never_makes_a_vendor_report_beside_a_company_date_and_clears_one_it_made():
    # the Oct 27 estimate passed with Yahoo's actual EPS on it: the same report as the company's Oct 26, so it is removed
    now = __import__("datetime").datetime(2026, 10, 28, 6, 46)
    res = resolve_past(date(2026, 10, 27), date(2026, 10, 28), [], [], [], [date(2026, 10, 27)], [], now, confirmed_future=[date(2026, 10, 26)])
    assert res.action == "superseded" and "confirmed Oct 26, 2026" in res.note
    assert vendor_report_beside_company(UHS_YAHOO[0], UHS_YAHOO[2], [], [date(2026, 10, 26)]) == date(2026, 10, 26)
    assert vendor_report_beside_company(UHS_YAHOO[0], UHS_YAHOO[2], [date(2026, 10, 27)], [date(2026, 10, 26)]) is None   # a reaction stands on it
    assert vendor_report_beside_company(UHS_YAHOO[0], "confirmed: press release", [], [date(2026, 10, 26)]) is None
    assert vendor_report_beside_company(UHS_YAHOO[0], UHS_YAHOO[2], [], [date(2026, 11, 26)]) is None


def test_one_preliminary_8k_rule_in_every_step_that_reads_a_release():
    emr = ("Item 2.02 Results of Operations and Financial Condition On October 13, 2026, Emerson Electric Co. announced that it has elected "
           "to change its method of accounting for actuarial gains and losses. Diluted earnings per share $1.08.")
    pru = ("Item 7.01 Regulation FD Disclosure. Prudential Financial, Inc. is furnishing this Current Report to disclose certain preliminary "
           "financial information regarding the quarter ended September 30, 2026. Net income per share is expected to be reduced by $0.40.")
    assert not is_results_release([emr]) and not is_results_release([pru])
    # the calendar, the missed-reports step and the release-EPS step call the same function
    assert "is_earnings_release" in (APP / "scripts" / "refresh_earnings_calendar.py").read_text()
    assert "is_earnings_release" in (APP / "scripts" / "catch_up_reports.py").read_text()
    assert "if not is_results_release([t for _, t in texts]):" in (APP / "scripts" / "seed_release_eps.py").read_text()
    assert "return is_results_release(texts)" in (APP / "services" / "earnings_release.py").read_text()


def test_one_stocks_failed_write_never_rolls_back_the_others(monkeypatch):
    import asyncio
    from datetime import date as _d
    from app.scripts import catch_up_reports as C
    from app.scripts import seed_historical_reactions as S

    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def commit(self): committed.append(current[0])
    committed, current = [], [None]

    async def ensure(session, tid, d, source):
        current[0] = tid
        if tid == "UHS":
            raise RuntimeError('duplicate key value violates unique constraint "uq_events_ticker_type_date"')
        return "event inserted"
    async def no_rows(*a, **k): return {}
    async def seed(sym): seeded.append(sym)
    seeded = []
    monkeypatch.setattr(C, "ScriptSessionLocal", Session)
    monkeypatch.setattr(C, "_ensure_event", ensure)
    monkeypatch.setattr(C, "_reaction_dates", no_rows)
    monkeypatch.setattr(S, "seed", seed)
    monkeypatch.setattr(C, "WRITES", C.WriteFailures(C.STEP_LABEL))
    missing = [C.Missing(s, _d(2026, 10, 20), "finnhub", 8) for s in ("ABT", "UHS", "ZTS")]
    asyncio.run(C.catch_up(missing, {"ABT": "ABT", "UHS": "UHS", "ZTS": "ZTS"}, write=True))
    assert committed == ["ABT", "ZTS"] and seeded == ["ABT", "ZTS"]
    assert [m.status for m in missing] == ["unseedable", "failed", "unseedable"]
    assert C.WRITES.rows and C.WRITES.rows[0].startswith("UHS@2026-10-20: ")
