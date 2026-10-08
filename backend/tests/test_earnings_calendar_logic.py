"""Earnings dates decided one way, with the confirmation level the page shows. NKE's exact rows on 2026-09-29."""
from datetime import date, datetime, timezone

from app.services.earnings_calendar import Candidate, level_of, merge_future, resolve_past

TODAY = date(2026, 9, 29)
NOW = datetime(2026, 9, 29, 16, 2, 47, tzinfo=timezone.utc)

# NKE, production, 2026-09-29: events Jun 25 (yf), Jun 30 (yf), Sep 28 (finnhub, estimated, passed), Dec 16 (finnhub);
# reactions Jun 30 (0.72 vs 0.13), Mar 31, Dec 18 2025; Finnhub calendar Sep 28 (no actual) + Dec 16; Yahoo Oct 1 16:00.
NKE_REACTIONS = [date(2025, 12, 18), date(2026, 3, 31), date(2026, 6, 30)]
NKE_FINNHUB = {date(2026, 12, 16): "unknown"}                      # Sep 28 is in the past part, with no actual EPS
NKE_YAHOO = {date(2026, 10, 1): "amc"}


def test_nke_next_is_yahoos_oct_1_estimate_and_dec_16_stays_as_a_later_estimate():
    cands = [Candidate(d, "finnhub", t) for d, t in NKE_FINNHUB.items()] + [Candidate(d, "yfinance", t) for d, t in NKE_YAHOO.items()]
    decided = merge_future(cands, last_report=date(2026, 6, 30), today=TODAY)
    assert [(f.day, f.confirmed, f.source, f.timing) for f in decided] == [
        (date(2026, 10, 1), False, "yfinance", "amc"), (date(2026, 12, 16), False, "finnhub", "unknown"),
    ]
    assert decided[0].note == "estimated (Yahoo Finance)"
    assert "quarterly report" not in decided[0].note    # Oct 1 is 93 days after Jun 30: not far


def test_nke_sep_28_estimate_is_superseded_by_the_oct_1_estimate_never_labelled_past():
    res = resolve_past(date(2026, 9, 28), TODAY, NKE_REACTIONS, [date(2026, 10, 1), date(2026, 12, 16)],
                       finnhub_actual_dates=[], yfinance_reported_dates=[date(2026, 6, 30)], edgar_202_dates=[], checked_at=NOW)
    assert res.action == "superseded" and res.report_date == date(2026, 10, 1)
    assert "replaced by the 2026-10-01 estimate" in res.note


def test_a_passed_estimate_with_no_alternative_and_no_evidence_is_unresolved_with_the_sources_checked():
    res = resolve_past(date(2026, 9, 28), TODAY, NKE_REACTIONS, [date(2026, 12, 16)], [], [date(2026, 6, 30)], [], NOW)
    assert res.action == "unresolved"
    assert res.note == "expected around 2026-09-28; not confirmed by Finnhub, Yahoo Finance or EDGAR"
    assert set(res.sources_checked) == {"finnhub", "yfinance", "edgar", "checked_at"}
    assert res.sources_checked["edgar"] == "no 8-K Item 2.02 filed since 2026-09-23"
    assert level_of(False, date(2026, 9, 29)) == "expected_unconfirmed"


def test_evidence_of_a_report_moves_the_estimate_to_the_report_date_and_confirms_it():
    finnhub = resolve_past(date(2026, 9, 28), TODAY, NKE_REACTIONS, [], [date(2026, 9, 29)], [], [], NOW)
    assert (finnhub.action, finnhub.report_date) == ("reported", date(2026, 9, 29)) and "Finnhub (actual EPS)" in finnhub.note
    edgar = resolve_past(date(2026, 9, 28), TODAY, NKE_REACTIONS, [], [], [], [date(2026, 9, 29)], NOW)
    assert (edgar.action, edgar.report_date) == ("reported", date(2026, 9, 29)) and "8-K Item 2.02" in edgar.note
    old_8k = resolve_past(date(2026, 9, 28), TODAY, NKE_REACTIONS, [], [], [], [date(2026, 9, 1)], NOW)
    assert old_8k.action == "unresolved", "an 8-K from before the window is not evidence for this estimate"


def test_a_stale_estimate_next_to_a_reaction_row_is_superseded():
    # ERIE: yfinance estimated Aug 6, the report happened Jul 30 and has its row
    res = resolve_past(date(2026, 8, 6), TODAY, [date(2026, 4, 23), date(2026, 7, 30)], [date(2026, 10, 28)], [], [], [], NOW)
    assert res.action == "superseded" and res.report_date == date(2026, 7, 30)


def test_two_sources_on_the_same_day_confirm_and_a_company_announcement_wins():
    agree = merge_future([Candidate(date(2026, 10, 29), "finnhub", "amc"), Candidate(date(2026, 10, 29), "yfinance", "unknown")], date(2026, 7, 30), TODAY)
    assert agree[0].confirmed and agree[0].note == "confirmed: Finnhub and Yahoo Finance agree" and agree[0].timing == "amc"
    differ = merge_future([Candidate(date(2026, 10, 28), "finnhub"), Candidate(date(2026, 10, 29), "yfinance", "amc")], date(2026, 7, 30), TODAY)
    assert not differ[0].confirmed and differ[0].day == date(2026, 10, 28)     # neither stored, both full sessions: the nearer day
    assert differ[0].note == "estimated (Finnhub); Yahoo Finance says 2026-10-29" and differ[0].timing == "amc"
    company = merge_future([Candidate(date(2026, 9, 28), "finnhub"), Candidate(date(2026, 10, 1), "yfinance", "amc"),
                            Candidate(date(2026, 10, 1), "company", "amc", "press release via Finnhub news 2026-08-28: NIKE, Inc. to Announce First Quarter Fiscal 2027 Results")],
                           date(2026, 6, 30), TODAY)
    assert [(f.day, f.confirmed) for f in company] == [(date(2026, 10, 1), True)]
    assert company[0].note.startswith("confirmed: press release via Finnhub news 2026-08-28")


def test_a_far_finnhub_date_alone_says_when_a_quarterly_report_would_usually_be_due():
    only_far = merge_future([Candidate(date(2026, 12, 16), "finnhub")], date(2026, 6, 30), TODAY)
    assert only_far[0].day == date(2026, 12, 16) and not only_far[0].confirmed
    assert "the last report was 2026-06-30, so a quarterly report would usually be due around 2026-09-29" in only_far[0].note
    # with a nearer estimate from any source, the nearer one is next and the far one is just a later date
    both = merge_future([Candidate(date(2026, 12, 16), "finnhub"), Candidate(date(2026, 10, 1), "yfinance", "amc")], date(2026, 6, 30), TODAY)
    assert both[0].day == date(2026, 10, 1) and "usually be due" not in both[0].note


def test_past_candidates_are_ignored_and_the_level_words_are_the_three_the_page_knows():
    assert merge_future([Candidate(date(2026, 9, 28), "finnhub")], None, TODAY) == []
    assert level_of(True, None) == "confirmed" and level_of(False, None) == "estimated"


# ── Source precedence: CCL, production, 2026-09-29 ────────────────────────────────────────────────────
# The catch-up step stored Sep 29 from EDGAR (8-K Item 2.02, filed the day CCL reported); Finnhub's calendar
# lists only Dec 18. The calendar step dropped Sep 29. It may not: a calendar source cannot outrank EDGAR.

def test_a_calendar_source_may_not_drop_an_edgar_date_a_reaction_row_or_an_actual_eps():
    from app.services.earnings_calendar import StoredDate, beyond_calendar_reach
    edgar = StoredDate(date(2026, 9, 29), "edgar", True, None)
    assert beyond_calendar_reach(edgar, [date(2026, 6, 23)], []) == "EDGAR"
    fin = StoredDate(date(2026, 9, 29), "finnhub", False, "estimated (Finnhub)")
    assert beyond_calendar_reach(fin, [date(2026, 9, 29)], []) == "reaction row"
    assert beyond_calendar_reach(fin, [date(2026, 6, 23)], [date(2026, 9, 30)]) == "actual EPS"
    assert beyond_calendar_reach(fin, [date(2026, 6, 23)], [date(2026, 9, 24)]) is None      # 5 days: not that report
    assert beyond_calendar_reach(StoredDate(date(2026, 9, 29), "manual", False, None), [], []) == "manual source"


def test_a_company_confirmation_is_kept_but_two_calendar_sources_agreeing_is_still_calendar_evidence():
    from app.services.earnings_calendar import AGREEMENT_NOTE, StoredDate, beyond_calendar_reach
    company = StoredDate(date(2026, 10, 29), "finnhub", True, "confirmed: 8-K Item 7.01 filed 2026-09-20")
    assert beyond_calendar_reach(company, [], []) == "company announcement"
    reported = StoredDate(date(2026, 9, 29), "finnhub", True, "reported on 2026-09-29 per Finnhub (actual EPS)")
    assert beyond_calendar_reach(reported, [], []) == "report evidence"
    agreed = StoredDate(date(2026, 10, 29), "finnhub", True, AGREEMENT_NOTE)
    assert beyond_calendar_reach(agreed, [], []) is None      # Finnhub and Yahoo may move what only they set
    unconfirmed = StoredDate(date(2026, 10, 29), "yfinance", False, "estimated (Yahoo Finance)")
    assert beyond_calendar_reach(unconfirmed, [], []) is None
    # the agreement note is the one merge_future writes, so the exemption cannot drift from it
    decided = merge_future([Candidate(date(2026, 10, 29), "finnhub"), Candidate(date(2026, 10, 29), "yfinance")], None, TODAY)
    assert decided[0].note == AGREEMENT_NOTE and decided[0].confirmed


# ── An empty or failed fetch is never evidence: production, 2026-09-29 ────────────────────────────────
# The Yahoo pass ran out of budget before the U-Z tail; the step then dropped UNH's Oct 13 for Finnhub's Jan 25
# and UBER's Nov 3 for nothing. Yahoo answers Oct 13 / Nov 3 / Oct 1 / Nov 25 when asked (probed 2026-09-30).

def test_unh_a_silent_yahoo_leaves_oct_13_standing_and_finnhubs_jan_25_is_the_following_estimate():
    from app.services.earnings_calendar import StoredDate, standing_candidates
    stored = [StoredDate(date(2026, 10, 13), "yfinance", False, "estimated (Yahoo Finance)", "bmo")]
    standing = standing_candidates(stored, answered={"finnhub"}, today=TODAY)
    assert [(c.day, c.source, c.timing, c.standing) for c in standing] == [(date(2026, 10, 13), "yfinance", "bmo", True)]
    decided = merge_future(standing + [Candidate(date(2027, 1, 25), "finnhub")], last_report=date(2026, 7, 16), today=TODAY)
    assert [(f.day, f.source, f.confirmed, f.note) for f in decided] == [
        (date(2026, 10, 13), "yfinance", False, "estimated (Yahoo Finance)"),
        (date(2027, 1, 25), "finnhub", False, "estimated (Finnhub)"),
    ]
    # once Yahoo answers with the same date, nothing stands in: Yahoo's word is its answer
    assert standing_candidates(stored, answered={"finnhub", "yfinance"}, today=TODAY) == []


def test_uber_a_silent_yahoo_and_a_silent_finnhub_leave_nov_3_standing():
    from app.services.earnings_calendar import StoredDate, standing_candidates
    stored = [StoredDate(date(2026, 11, 3), "yfinance", False, "estimated (Yahoo Finance)", "bmo")]
    decided = merge_future(standing_candidates(stored, set(), TODAY), last_report=date(2026, 8, 5), today=TODAY)
    assert [(f.day, f.source, f.note) for f in decided] == [(date(2026, 11, 3), "yfinance", "estimated (Yahoo Finance)")]


def test_nke_with_yahoo_silent_dec_16_stands_and_nothing_else_is_decided():
    from app.services.earnings_calendar import StoredDate, standing_candidates
    stored = [StoredDate(date(2026, 12, 16), "finnhub", False, "estimated (Finnhub)")]
    cands = [Candidate(date(2026, 12, 16), "finnhub")] + standing_candidates(stored, answered={"finnhub"}, today=TODAY)
    decided = merge_future(cands, last_report=date(2026, 6, 30), today=TODAY)
    assert [(f.day, f.source) for f in decided] == [(date(2026, 12, 16), "finnhub")]
    assert "usually be due around 2026-09-29" in decided[0].note


def test_a_nearer_stored_estimate_outranks_a_farther_calendar_date_for_the_same_quarter():
    from app.services.earnings_calendar import SAME_REPORT_DAYS, StoredDate, standing_candidates
    # VEEV: Yahoo's Nov 25 stands (Yahoo silent); Finnhub says Nov 18: one report, Yahoo's day, Finnhub's in the note
    stored = [StoredDate(date(2026, 11, 25), "yfinance", False, "estimated (Yahoo Finance)", "amc")]
    decided = merge_future(standing_candidates(stored, {"finnhub"}, TODAY) + [Candidate(date(2026, 11, 18), "finnhub")], None, TODAY)
    assert [(f.day, f.source, f.note) for f in decided] == [(date(2026, 11, 25), "yfinance", "estimated (Yahoo Finance); Finnhub says 2026-11-18")]
    # a stored Finnhub estimate with Finnhub silent and Yahoo naming another full session in the same quarter: the stored date stands
    stored = [StoredDate(date(2026, 10, 13), "finnhub", False, "estimated (Finnhub)")]
    decided = merge_future(standing_candidates(stored, {"yfinance"}, TODAY) + [Candidate(date(2026, 10, 20), "yfinance")], None, TODAY)
    assert [(f.day, f.source, f.note) for f in decided] == [(date(2026, 10, 13), "finnhub", "estimated (Finnhub); Yahoo Finance says 2026-10-20")]
    # the same source returning a different date is a retraction: nothing stands in for it
    assert standing_candidates(stored, {"finnhub"}, TODAY) == []
    assert [f.day for f in merge_future([Candidate(date(2027, 1, 25), "finnhub")], None, TODAY)] == [date(2027, 1, 25)]
    assert SAME_REPORT_DAYS == 60


def test_a_date_two_sources_agreed_on_stands_for_each_that_is_silent():
    from app.services.earnings_calendar import AGREEMENT_NOTE, StoredDate, standing_candidates
    stored = [StoredDate(date(2026, 10, 29), "finnhub", True, AGREEMENT_NOTE, "amc")]
    both = standing_candidates(stored, set(), TODAY)
    assert sorted((c.source, c.day) for c in both) == [("finnhub", date(2026, 10, 29)), ("yfinance", date(2026, 10, 29))]
    assert merge_future(both, None, TODAY)[0].note == AGREEMENT_NOTE
    only_yahoo_silent = standing_candidates(stored, {"finnhub"}, TODAY)
    assert [c.source for c in only_yahoo_silent] == ["yfinance"]
    # past dates and dates beyond a calendar source's reach are not candidates
    assert standing_candidates([StoredDate(date(2026, 9, 28), "finnhub", False, None), StoredDate(date(2026, 10, 1), "edgar", True, None)], set(), TODAY) == []


# ── Tie rule: two calendar estimates for one quarter, neither confirmed ────────────────────────────────────

def test_adsk_a_half_day_loses_the_tie_and_dri_christmas_eve_loses_it():
    from app.services.trading_calendar import is_half_day, is_trading_day
    assert is_half_day(date(2026, 11, 27)) and not is_trading_day(date(2026, 11, 26))      # the Friday after Thanksgiving
    assert is_half_day(date(2026, 12, 24)) and not is_trading_day(date(2026, 12, 25))
    assert not is_trading_day(date(2026, 7, 3)) and not is_half_day(date(2026, 7, 3))      # July 4 2026 is a Saturday: July 3 is the holiday
    assert is_half_day(date(2025, 7, 3)) and not is_half_day(date(2026, 11, 23)) and not is_half_day(date(2026, 12, 16))
    assert not is_trading_day(date(2026, 10, 3)) and is_trading_day(date(2026, 10, 2))
    # ADSK: Finnhub Nov 23, Yahoo Nov 27 (the half day), whichever is stored
    for standing in ("finnhub", "yfinance"):
        cands = [Candidate(date(2026, 11, 23), "finnhub", standing=standing == "finnhub"),
                 Candidate(date(2026, 11, 27), "yfinance", "amc", standing=standing == "yfinance")]
        decided = merge_future(cands, None, TODAY)
        assert [(f.day, f.source, f.note) for f in decided] == [(date(2026, 11, 23), "finnhub", "estimated (Finnhub); Yahoo Finance says 2026-11-27")], standing
    # DRI: Dec 16 vs Dec 24
    decided = merge_future([Candidate(date(2026, 12, 24), "finnhub"), Candidate(date(2026, 12, 16), "yfinance", "bmo")], None, TODAY)
    assert [(f.day, f.source, f.note) for f in decided] == [(date(2026, 12, 16), "yfinance", "estimated (Yahoo Finance); Finnhub says 2026-12-24")]
    # a weekend loses too
    decided = merge_future([Candidate(date(2026, 10, 24), "yfinance", standing=True), Candidate(date(2026, 10, 22), "finnhub")], None, TODAY)
    assert decided[0].day == date(2026, 10, 22) and decided[0].note == "estimated (Finnhub); Yahoo Finance says 2026-10-24"


def test_a_plain_disagreement_keeps_the_stored_date_and_notes_the_other_with_no_source_preferred():
    stored_yahoo = merge_future([Candidate(date(2026, 10, 27), "finnhub"), Candidate(date(2026, 10, 29), "yfinance", standing=True)], None, TODAY)
    assert (stored_yahoo[0].day, stored_yahoo[0].source, stored_yahoo[0].note) == (date(2026, 10, 29), "yfinance", "estimated (Yahoo Finance); Finnhub says 2026-10-27")
    stored_finnhub = merge_future([Candidate(date(2026, 10, 29), "finnhub", standing=True), Candidate(date(2026, 10, 27), "yfinance")], None, TODAY)
    assert (stored_finnhub[0].day, stored_finnhub[0].source, stored_finnhub[0].note) == (date(2026, 10, 29), "finnhub", "estimated (Finnhub); Yahoo Finance says 2026-10-27")
    # neither stored (a first run): the nearer day, whichever source
    fresh = merge_future([Candidate(date(2026, 10, 29), "finnhub"), Candidate(date(2026, 10, 27), "yfinance")], None, TODAY)
    assert (fresh[0].day, fresh[0].source) == (date(2026, 10, 27), "yfinance")
    fresh = merge_future([Candidate(date(2026, 10, 27), "finnhub"), Candidate(date(2026, 10, 29), "yfinance")], None, TODAY)
    assert (fresh[0].day, fresh[0].source, fresh[0].note) == (date(2026, 10, 27), "finnhub", "estimated (Finnhub); Yahoo Finance says 2026-10-29")
    # the same day is still agreement, and a company announcement still wins
    assert merge_future([Candidate(date(2026, 10, 29), "finnhub"), Candidate(date(2026, 10, 29), "yfinance")], None, TODAY)[0].confirmed


def test_fdx_sep_16_estimate_is_removed_once_the_company_confirms_oct_28():
    """FDX: the Sep 16 Finnhub estimate passed with no report (no 8-K Item 2.02, no actual EPS); the company then announced Oct 28,
    42 days later and inside the same-report window. The estimate is the same report under the wrong date, so it is removed."""
    res = resolve_past(date(2026, 9, 16), date(2026, 10, 8), [date(2026, 6, 23)], [date(2026, 12, 16)], [], [], [], NOW,
                       confirmed_future=[date(2026, 10, 28), date(2026, 12, 16)])
    assert res.action == "superseded" and res.report_date == date(2026, 10, 28)
    assert res.note == "the company confirmed 2026-10-28 for this report; the 2026-09-16 estimate is removed"
    # a confirmed date a full quarter later is the next report, not this one: the estimate stays unresolved
    assert resolve_past(date(2026, 9, 16), date(2026, 10, 8), [date(2026, 6, 23)], [], [], [], [], NOW, confirmed_future=[date(2026, 12, 16)]).action == "unresolved"
    assert resolve_past(date(2026, 9, 16), date(2026, 10, 8), [date(2026, 6, 23)], [], [], [], [], NOW).action == "unresolved"

