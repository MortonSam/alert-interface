"""report_date_reader.classify_quote (Sam, 2026-10-20): only a release date in the company's own words confirms or changes a date;
a call date alone leaves it estimated, and text the company didn't issue is ignored. The worked examples are last night's quotes."""
import inspect
from datetime import date

from app.scripts import confirm_report_dates as C
from app.services import report_date_reader as R

TODAY = date(2026, 10, 20)


def cls(kind, text, symbol):
    hit = R.read_release_date(text, TODAY) or R.read_report_date(text, TODAY)
    assert hit is not None, text
    return R.classify_quote(kind, text, hit.sentence, hit.day, symbol, TODAY), hit.day


def test_call_dates_leave_the_date_estimated():
    # Tyler: the call is Oct 29; its release comes after the close on Oct 28
    tyl = ("Tyler Technologies Schedules Third Quarter 2026 Earnings Conference Call and Webcast. PLANO, Texas, October 13, 2026--Tyler "
           "Technologies will discuss its third quarter 2026 results during a conference call and webcast on Thursday, October 29, 2026.")
    assert cls("press release", tyl, "TYL") == ("call_only", date(2026, 10, 29))
    # Veralto: the call is Oct 30; the release is posted after the close on Oct 29
    vlto = ("Veralto Schedules Third Quarter 2026 Earnings Call. Veralto Corporation (NYSE: VLTO), a global leader in essential water and product "
            "quality solutions, announced that it will webcast its third quarter 2026 earnings conference call on Friday, October 30, 2026, "
            "beginning at 7:30 a.m. ET.")
    assert cls("press release", vlto, "VLTO") == ("call_only", date(2026, 10, 30))
    aee = ("Ameren Corporation Third Quarter 2026 Earnings Webcast set for Nov. 6, 2026. Martin J. Lyons Jr., chairman, president and CEO of "
           "Ameren Corp. (NYSE: AEE), and Leonard P. Singh, executive vice president and CFO of Ameren Corp., will discuss Third Quarter 2026 "
           "earnings, earnings guidance and other matters in a conference call with financial analysts at 9 a.m. Central time (10 a.m. Eastern "
           "time) on Friday, Nov. 6, 2026.")
    assert cls("press release", aee, "AEE") == ("call_only", date(2026, 11, 6))
    apa = ("Third-quarter 2026 earnings call APA will host a conference call to discuss its third-quarter 2026 results at 10 a.m. Central "
           "time, Thursday, Nov. 5.")
    assert cls("8-K exhibit", apa, "APA") == ("call_only", date(2026, 11, 5))
    bkng = ("Booking Holdings (NASDAQ: BKNG) announced today that it intends to hold a conference call to discuss its third quarter 2026 "
            "financial results on Tuesday, November 3 at 4:30 p.m. ET.")
    assert cls("press release", bkng, "BKNG")[0] == "call_only"


def test_a_release_date_in_the_companys_own_words_confirms():
    uhs = ("KING OF PRUSSIA, Pa., Oct. 05, 2026 (GLOBE NEWSWIRE) -- Universal Health Services, Inc. (NYSE: UHS) announced today that it will "
           "report results for its third quarter ended September 30, 2026, after the market closes on Monday, October 26, 2026. There will be a "
           "conference call for investors and analysts on Tuesday, October 27, 2026, at 9:30 a.m. Eastern Time.")
    assert cls("press release", uhs, "UHS") == ("release", date(2026, 10, 26))
    tsla = "Tesla will post its financial results for the third quarter of 2026 after market close on Wednesday, October 21, 2026."
    assert cls("8-K exhibit", tsla, "TSLA") == ("release", date(2026, 10, 21))
    abt = "Abbott (NYSE: ABT) will announce its third-quarter 2026 financial results on Wednesday, Oct. 21, before the market opens."
    assert cls("press release", abt, "ABT") == ("release", date(2026, 10, 21))
    aos = ("A. O. Smith Corporation (NYSE: AOS) will release its third quarter 2026 financial results before the market opens on Thursday, "
           "Oct. 29, and has scheduled an investor conference call to follow at 10:00 a.m. (Eastern Daylight Time).")
    assert cls("press release", aos, "AOS") == ("release", date(2026, 10, 29))


def test_text_the_company_did_not_issue_is_ignored():
    ajg = ("Gallagher (AJG) is back in focus as the insurer prepares to report fiscal third quarter results on October 29, with analysts "
           "expecting profit per share to be about 30% higher year over year.")
    assert cls("press release", ajg, "AJG")[0] == "third_party"
    biib = ("Biogen Inc (NASDAQ:BIIB, XETRA:IDP) is expected to report a slight third-quarter earnings per share beat at $2.14, against a "
            "consensus of $2.07, when it reports on October 28, says Jefferies.")
    assert cls("press release", biib, "BIIB")[0] == "third_party"
    # the same words with no wire dateline and no exchange tag of its own are not the company's either
    assert not R.company_issued("press release", "Abbott will announce its third-quarter 2026 results on Wednesday, Oct. 21.", "ABT")
    assert R.company_issued("8-K exhibit", "anything the company filed", "ZZ") and R.company_issued("IR feed", "its own page", "ZZ")


def test_the_model_cannot_confirm_a_call_and_only_the_release_class_is_written():
    vlto = "Veralto will webcast its third quarter 2026 earnings conference call on Friday, October 30, 2026, beginning at 7:30 a.m. ET."
    pattern = R.ReadDate(date(2026, 10, 30), "bmo", "third quarter", vlto)
    day, note = R.decide(pattern, {"date": date(2026, 10, 30), "timing": "bmo", "quote": vlto}, vlto, TODAY)
    assert day is None and "names a call" in note
    src = inspect.getsource(C.main)
    assert 'if write and cls == "release":' in src and 'if cls != "release":' in src
    assert R.READER_VERSION == 3 and R.QUOTE_CLASSES == ("release", "call_only", "third_party")
