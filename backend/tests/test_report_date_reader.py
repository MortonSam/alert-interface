"""The report-date reader (services/report_date_reader): a company's own sentence sets its earnings date, two readers must agree,
and nothing writes without both --write and CONFIRMATION_READER_WRITE=true."""
from datetime import date

from app.scripts.confirm_report_dates import STEP_LABEL, classify, writes_allowed
from app.services import report_date_reader as R

TODAY = date(2026, 10, 12)
TSLA = ("Q3 2026 Production Deliveries Subject to operating lease accounting Model 3/Y 457,387 478,237 1% Other Models 7,004 8,295 4% Total 464,391 "
        "486,532 1% *** Tesla will post its financial results for the third quarter of 2026 after market close on Wednesday, October 21, 2026. "
        "At that time, Tesla will issue a brief advisory containing a link to the Q3 2026 update.")


def test_teslas_deliveries_release_names_its_results_date():
    r = R.read_report_date(TSLA, TODAY)
    assert r is not None and (r.day, r.timing) == (date(2026, 10, 21), "amc") and r.quarter.lower() == "third quarter"
    assert r.sentence.startswith("Tesla will post its financial results for the third quarter of 2026 after market close on Wednesday, October 21, 2026")


def test_before_open_after_close_and_clock_times():
    bmo = "JPMorgan Chase will report its third-quarter 2026 financial results on Tuesday, October 14, 2026 before the market opens."
    assert R.read_report_date(bmo, TODAY).timing == "bmo"
    clock = "Citigroup Inc. plans to release its third quarter 2026 earnings on October 14, 2026 at 8:00 a.m. ET."
    assert R.read_report_date(clock, TODAY).timing == "bmo"
    late = "Netflix, Inc. will post its fourth quarter 2026 results at 4:05 p.m. PT on January 20, 2027."
    assert R.read_report_date(late, TODAY).timing == "amc"
    assert R.timing_of("Results will be discussed on a call at 10:00 a.m. Eastern") == "unknown"


def test_the_forms_the_2026_10_12_sample_of_estimated_dates_announced_in():
    """What the 20 sampled companies had already published while the calendar still called their dates estimates."""
    csx = "CSX Corp. (NASDAQ: CSX) will release third quarter financial and operating results after the market close on Wednesday, Oct. 21, 2026."
    assert (R.read_report_date(csx, TODAY).day, R.read_report_date(csx, TODAY).timing) == (date(2026, 10, 21), "amc")        # "Oct." is October, not November
    gehc = ("GE HealthCare to announce third quarter 2026 results on October 28, 2026. CHICAGO, October 07, 2026--GE HealthCare (Nasdaq: GEHC) will announce "
            "its third quarter 2026 financial results before the market opens on Wednesday, October 28, 2026.")
    assert R.read_report_date(gehc, TODAY).timing == "bmo"                                                                      # the body's timing, not the headline's silence
    ldos = ("Leidos (NYSE: LDOS) today announced it has scheduled a conference call for Tuesday, November 3, 2026, at 8 a.m. (ET) to announce its third quarter "
            "2026 financial results for the period ending October 2, 2026.")
    assert (R.read_report_date(ldos, TODAY).day, R.read_report_date(ldos, TODAY).timing) == (date(2026, 11, 3), "bmo")          # the call announces the results; the period date is not the day
    txn = "Texas Instruments Incorporated (TI) (Nasdaq: TXN) will webcast its third quarter earnings conference call on Wednesday, Oct. 21, at 3:30 p.m. Central time."
    assert (R.read_report_date(txn, TODAY).day, R.read_report_date(txn, TODAY).timing) == (date(2026, 10, 21), "amc")           # no year in the sentence; 3:30 Central is after the close
    hona = "Honeywell Aerospace (Nasdaq: HONA) will issue third quarter financial results after the closing of the Nasdaq Stock Market on Wednesday, October 28."
    assert R.read_report_date(hona, TODAY).timing == "amc"


def test_a_past_date_a_period_date_a_call_only_sentence_and_no_quarter_read_nothing():
    assert R.read_report_date("Tesla will post its financial results for the third quarter of 2026 after market close on Wednesday, October 7, 2026.", TODAY) is None
    period = "The company will report results for the quarter ended September 30, 2026 in due course."
    assert R.read_report_date(period, TODAY) is None
    call = "The company will host a conference call on Wednesday, October 21, 2026 at 5:30 p.m. Eastern Time."
    assert R.read_report_date(call, TODAY) is None                                 # no results word: a call is not a results date
    no_quarter = "Tesla will post its financial results after market close on Wednesday, October 21, 2026."
    assert R.read_report_date(no_quarter, TODAY) is None
    far = "The company will release its fourth-quarter results on March 3, 2027."
    assert R.read_report_date(far, TODAY) is None                                  # beyond the horizon


def test_the_model_quote_must_be_verbatim_and_name_the_date_and_both_readers_must_agree():
    hit = R.read_report_date(TSLA, TODAY)
    good = {"date": date(2026, 10, 21), "timing": "amc", "quote": "Tesla will post its financial results for the third quarter of 2026 after market close on Wednesday, October 21, 2026."}
    assert R.verify_quote(TSLA, good["quote"], good["date"]) == []
    assert R.decide(hit, good, TSLA, TODAY) == (date(2026, 10, 21), "both readers 2026-10-21")
    paraphrase = {**good, "quote": "Tesla will report Q3 results on October 21, 2026 after the close."}
    assert R.decide(hit, paraphrase, TSLA, TODAY)[0] is None and "not verbatim" in R.decide(hit, paraphrase, TSLA, TODAY)[1]
    other_day = {**good, "date": date(2026, 10, 22)}
    assert "quote does not name 2026-10-22" in R.decide(hit, other_day, TSLA, TODAY)[1]
    disagree = {"date": date(2026, 10, 22), "timing": "amc", "quote": "At that time, Tesla will issue a brief advisory containing a link to the Q3 2026 update."}
    assert "quote does not name" in R.decide(hit, disagree, TSLA, TODAY)[1]
    assert R.decide(hit, None, TSLA, TODAY) == (None, "pattern 2026-10-21 (amc); no model reading")
    assert R.decide(None, good, TSLA, TODAY)[0] is None                           # the pattern reader must agree too
    assert R.parse_model_json('{"date": "2026-10-21", "timing": "AMC", "quote": "x"}') == {"date": date(2026, 10, 21), "timing": "amc", "quote": "x"}
    assert R.parse_model_json("no json") is None


def test_the_calendar_note_reads_as_the_page_expects_and_the_write_is_double_gated():
    assert R.confirmation_note("8-K exhibit", "Item 2.02, 9.01 exhibit991.htm", "2026-10-02", "Tesla will post ... October 21, 2026.").startswith("confirmed: 8-K Item 2.02, 9.01 exhibit991.htm filed 2026-10-02: Tesla will post")
    assert R.confirmation_note("press release", "https://x", "2026-10-02", "q").startswith("confirmed: press release via Finnhub news 2026-10-02: q")
    assert R.confirmation_note("IR feed", "https://ir.example/x", "2026-10-02", "q").startswith("confirmed: press release via IR feed 2026-10-02 https://ir.example/x: q")
    assert not writes_allowed(["--write"], {}) and not writes_allowed([], {"CONFIRMATION_READER_WRITE": "true"}) and writes_allowed(["--write"], {"CONFIRMATION_READER_WRITE": "true"})
    stored = [{"event_date": date(2026, 10, 21), "is_confirmed": False}, {"event_date": date(2027, 1, 27), "is_confirmed": True}]
    assert classify(date(2026, 10, 21), stored)[0] == "confirms"
    assert classify(date(2026, 10, 22), stored)[0] == "changes"
    assert classify(date(2027, 1, 28), stored)[0] == "contradicts"
    assert classify(date(2027, 4, 28), stored)[0] == "new"
    from app.scripts import refresh
    labels = [l for l, _ in refresh.STEPS]
    # after the calendar whose dates it confirms; EPS actuals keeps the slot right after the calendar (test_eps_actuals)
    assert STEP_LABEL in labels and labels.index(STEP_LABEL) > labels.index("Refresh earnings calendar (Finnhub)")
