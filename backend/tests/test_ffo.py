"""FFO per share for REITs (services/ffo): two readers agreeing to the cent, the XBRL cross-check that holds a figure past 5%, and the
year-ago line every page reads (2026-10-15)."""
from datetime import date

from app.services import ffo as F
from app.services.eps_year_ago import eps_line, year_ago_pairs
from app.services.licensed_estimates import YearAgo, year_ago_fields

O_TABLE = ("Amounts available to common stockholders per common share: Net income per common share, basic and diluted $ 0.37 $ 0.22 "
           "FFO per common share: Basic $ 1.07 $ 1.06 Diluted $ 1.07 $ 1.06 Normalized FFO per common share: Basic $ 1.07 $ 1.06 "
           "Diluted $ 1.07 $ 1.06 AFFO per common share: Basic $ 1.10 $ 1.05 Diluted $ 1.10 $ 1.05")


def test_is_reit_reads_gics():
    assert F.is_reit("Real Estate", "Retail REITs") and F.is_reit("Real Estate", "REIT - Residential")
    assert not F.is_reit("Real Estate", "Real Estate Services") and not F.is_reit("Financials", "Mortgage REITs")


def test_pattern_reads_nareit_ffo_never_core_normalized_affo_or_guidance():
    assert F.parse_release_ffo("For the quarter, Nareit FFO was $1.13 per diluted share, compared to $1.09.")["ffo"] == 1.13
    assert F.parse_release_ffo("Core FFO of $1.40 per diluted share.") is None
    assert F.parse_release_ffo("Normalized FFO was $0.98 per share.") is None
    assert F.parse_release_ffo("The company raises full year 2026 FFO guidance to a range of $12.45 to $12.55 per share.") is None
    got = F.parse_release_ffo(O_TABLE)
    assert got["ffo"] == 1.07 and got["how"] == "table row, diluted"


def test_a_basic_first_row_is_read_at_its_diluted_figure():
    assert F.parse_release_ffo("FFO per share: Basic $ 7.04 $ 6.91 Diluted $ 7.03 $ 6.90")["ffo"] == 7.03


def test_the_model_quote_must_be_verbatim_and_under_nareit_ffo():
    assert F.verify_ffo_quote(O_TABLE, "Diluted $ 1.07 $ 1.06", 1.07) == []                  # a bare row under "FFO per common share"
    assert F.verify_ffo_quote(O_TABLE, "Diluted $ 1.10 $ 1.05", 1.10) != []                  # the AFFO row: never
    assert "the quote is not verbatim in the exhibit" in F.verify_ffo_quote(O_TABLE, "FFO per share $1.07", 1.07)
    assert F.verify_ffo_quote(O_TABLE, None, None) == ["model read nothing"]


def test_both_readers_must_agree_to_the_cent():
    pattern = {"ffo": 1.07, "how": "table row"}
    assert F.decide_ffo(pattern, {"ffo": 1.07, "quote": "Diluted $ 1.07 $ 1.06"}, O_TABLE) == (1.07, "both readers 1.07")
    figure, note = F.decide_ffo({"ffo": 7.04, "how": "table row"}, {"ffo": 7.03, "quote": "x"}, "x FFO x")
    assert figure is None and ("rejected" in note or "disagree" in note)
    assert F.decide_ffo(pattern, None, O_TABLE)[0] is None


def _facts(ni, da, gains, impair, shares, end="2026-06-30", start="2026-04-01"):
    def series(v, unit="USD"):
        return {"units": {unit: [{"start": start, "end": end, "filed": "2026-08-01", "val": v}]}}
    g = {"NetIncomeLossAvailableToCommonStockholdersBasic": series(ni), "DepreciationDepletionAndAmortization": series(da),
         "WeightedAverageNumberOfDilutedSharesOutstanding": series(shares, "shares")}
    if gains is not None:
        g["GainLossOnSaleOfProperties"] = series(gains)
    if impair is not None:
        g["ImpairmentOfRealEstate"] = series(impair)
    return {"facts": {"us-gaap": g}}


def test_xbrl_ffo_is_net_income_plus_depreciation_and_impairments_less_gains_over_diluted_shares():
    # worked example: (330 + 640 + 40 - 20) / 925 = 1.0703
    x = F.xbrl_ffo_quarters(_facts(330e6, 640e6, 20e6, 40e6, 925e6))[date(2026, 6, 30)]
    assert x["ffo_per_share"] == 1.0703
    assert F.cross_check(1.07, x)[0] == "ok"
    state, gap, reason = F.cross_check(1.07, F.xbrl_ffo_quarters(_facts(330e6, 500e6, 20e6, None, 925e6))[date(2026, 6, 30)])
    assert state == "held" and gap > F.FFO_GAP_PCT and "over 5%" in reason          # (330 + 500 - 20) / 925 = 0.8757: 22% apart
    assert F.cross_check(1.07, None)[0] == "ok"                                      # no tags: the agreed reading stands, said in the reason


def test_the_year_ago_line_says_ffo_per_share_and_a_held_quarter_says_so():
    pairs = [{**p, "measure": F.MEASURE} for p in year_ago_pairs([(date(2025, 6, 30), 1.06), (date(2026, 6, 30), 1.07)])]
    assert eps_line(pairs[0]) == "FFO per share $1.07, up 0.9% from $1.06 a year ago"
    assert eps_line(pairs[1]) == "FFO per share $1.06. No FFO figure from the same quarter a year earlier is on file."
    ya = YearAgo(pairs, {date(2026, 3, 31): {"period_end": date(2026, 3, 31), "measure": F.MEASURE, "held_line": F.HELD_LINE.format(gap=7.24)}})
    assert ya.for_report(date(2026, 8, 5))["measure"] == "FFO per share"
    held = ya.for_report(date(2026, 5, 6))
    assert held["sec_eps"] is None and held["eps_line"] == ("FFO per share for this quarter is held because the release's figure and the one "
                                                            "computed from the company's filings differ by 7.2%.")
    assert year_ago_fields(None)["measure"] is None


# ── the readers fixed on 2026-10-16, each on the text of the release that failed (backend/ops/reports/walkthrough_2026-10-15/ffo_coverage_v2.md)

def _ffo(text):
    got = F.parse_release_ffo(text)
    return got and got["ffo"]


def test_labels_read_in_any_case_and_after_footnotes():
    assert _ffo("Funds from operations (FFO) per Share - diluted (1) $ 2.10 $ 2.19 $ 4.32") == 2.10                    # MAA
    assert _ffo("Funds from operations per share attributable to Alexandria’s common stockholders – diluted 2.44 3.73 1.93") == 2.44   # ARE


def test_a_basic_row_is_skipped_for_the_diluted_one():
    assert _ffo("Basic FFO per share (11) $ 8.66 $ 7.70 $ 7.04 Diluted FFO per share (11) $ 8.61 $ 7.68 $ 7.03") == 8.61   # EQIX


def test_an_adjustments_row_is_never_the_figure():
    assert _ffo("Nareit FFO adjustments per share $ 0.85 $ 0.71 Nareit FFO attributable to common stockholders per share $ 0.99 $ 0.86") == 0.99   # VTR


def test_a_row_under_a_per_share_heading_and_a_total_then_per_share_row():
    assert _ffo("Per diluted share data attributable to common stockholders: Net income (loss) (4) $ 0.61 $ 0.45 NAREIT FFO $ 1.56 $ 1.24 "
                "Normalized FFO $ 1.60 $ 1.28") == 1.56                                                                    # WELL
    assert _ffo("Per Share Amounts (Fully Diluted Shares): FFO (Nareit) $0.76 $0.89 (14.6) % FFO (Normalized) $1.01 $0.99") == 0.76   # IRM
    assert _ffo("(in thousands, except per share) FFO $ 298,556 $ 2.81 $ 339,175 $ 3.14 Adjustments to FFO:") == 2.81            # SBAC


def test_real_estate_ffo_a_comparison_guidance_and_another_period_are_never_the_figure():
    spg = ("Results for the Quarter ​ • Real Estate Funds From Operations (“Real Estate FFO”) was $1.249 billion, or $3.29 per "
           "diluted share as compared to $1.154 billion, or $3.05 per diluted share. ​ • Funds From Operations (“FFO”) was "
           "$1.185 billion, or $3.12 per diluted share as compared to $1.189 billion, or $3.15 per diluted share in the prior year.")
    assert _ffo(spg) == 3.12                                                                                              # SPG
    assert _ffo("Results for the Six Months • FFO was $2.194 billion, or $5.82 per diluted share") is None
    assert _ffo("an increase, compared to FFO of $271.7 million, or $1.71 per diluted share, for the second quarter of 2025") is None
    bxp = ("FFO per Share Guidance: BXP’s guidance for the third quarter and full year 2026 is set forth below. Third Quarter 2026 Full Year "
           "2026 FFO per share (diluted) $ 1.80 $ 1.82 $ 6.99 $ 7.05 " + "(development and leasing activity) " * 8 + "Three Months Ended June 30, 2026 2025 FFO per share basic $ 1.78 $ 1.72 "
           "FFO per share diluted $ 1.78 $ 1.71")
    assert _ffo(bxp) == 1.78                                                                                              # BXP


def test_the_derived_reading_divides_the_nareit_total_by_the_quarters_diluted_shares():
    # AMT: $1,249.3 million over 466,265 thousand diluted shares = 2.6794, read at 2.68; the outlook's "467,000 – 467,000" is a range
    amt = ("Nareit Funds From Operations (FFO) attributable to AMT common stockholders (1) $ 1,249 63.4 % ... Divided by weighted average diluted "
           "shares outstanding (in thousands) 467,000 – 467,000 ... ($ in millions, except share and per share data) Nareit FFO attributable to "
           "AMT common stockholders $ 1,249.3 $ 764.7 Straight-line revenue 18.9 ... Divided by weighted average diluted shares outstanding "
           "(in thousands) 466,265 468,791 AFFO attributable to AMT common stockholders per Share $ 2.71 $ 2.60")
    got = F.parse_release_ffo(amt)
    assert got["ffo"] == 2.68 and got["how"] == F.DERIVED_HOW and got["total"] == 1_249.3e6 and got["shares"] == 466_265e3
    # PLD: in thousands, the diluted share row before the total: 1,632,356 / 957,884 = 1.7041
    pld = ("in thousands, except per share amount Weighted average common shares outstanding - Diluted 957,884 955,882 Net earnings per share "
           "- Diluted $ 1.13 $ 0.61 ... NAREIT defined FFO attributable to common stockholders/unitholders* $ 1,632,356 $ 1,277,354 Core FFO per "
           "share - Diluted $ 1.63")
    got = F.parse_release_ffo(pld)
    assert got["ffo"] == 1.63 or got["how"] == F.DERIVED_HOW                       # a stated Core figure is never read
    assert F.parse_release_ffo(pld.replace("Core FFO per share - Diluted $ 1.63", ""))["ffo"] == 1.70


def test_a_derived_figure_needs_the_model_to_derive_the_same_from_verbatim_rows():
    amt = ("($ in millions) Nareit FFO attributable to AMT common stockholders $ 1,249.3 $ 764.7 ... Divided by weighted average diluted shares "
           "outstanding (in thousands) 466,265 468,791")
    pattern = F.parse_release_ffo(amt)
    model = {"ffo": None, "total": 1249.3, "total_unit": "millions", "total_quote": "Nareit FFO attributable to AMT common stockholders $ 1,249.3 $ 764.7",
             "shares": 466265, "shares_unit": "thousands", "shares_quote": "Divided by weighted average diluted shares outstanding (in thousands) 466,265 468,791"}
    assert F.decide_ffo(pattern, model, amt) == (2.68, f"both readers 2.68 ({F.DERIVED_HOW})")
    assert F.decide_ffo(pattern, {**model, "shares": 468791, "shares_quote": "466,265 468,791"}, amt)[0] is None     # another column
    assert F.decide_ffo(pattern, {"ffo": 2.68, "quote": "x"}, amt)[0] is None              # a stated reading never pairs with a derived one


def test_the_verbatim_check_reads_curly_quotes_as_straight_and_the_release_reads_before_its_supplement():
    text = "Funds From Operations (“FFO”) was $1.185 billion, or $3.12 per diluted share"
    assert F.verify_ffo_quote(text, 'Funds From Operations ("FFO") was $1.185 billion, or $3.12 per diluted share', 3.12) == []
    supp = ("q42025supplement.htm", "Q1 Q2 Q3 Q4 FFO (c)(d) $ 1.10 $ 1.00 $ 1.07 $ 1.11 $ 1.03 $ 0.98 $ 1.01 $ 1.01 " + "x" * 600)
    release = ("q42025earningsrelease.htm", "For the Three Months Ended December 31, 2025 FFO (c)(d) $ 1.01 $ 1.11 $ 4.04 $ 4.28")
    assert F.parse_release_ffo_all([supp, release])[0]["ffo"] == 1.01                    # CCI


def test_a_derived_figure_says_so_and_an_unread_quarter_says_why_it_is_held():
    pairs = [{**p, "measure": F.MEASURE, "note": F.DERIVED_NOTE} for p in year_ago_pairs([(date(2025, 6, 30), 1.63), (date(2026, 6, 30), 2.68)])]
    assert eps_line(pairs[0]) == "FFO per share $2.68 (the release's Nareit FFO over its diluted shares), up 64.4% from $1.63 a year ago"
    ya = YearAgo(pairs, {date(2026, 3, 31): {"period_end": date(2026, 3, 31), "measure": F.MEASURE, "held_line": F.UNREAD_LINE}})
    assert ya.for_report(date(2026, 4, 28))["eps_line"] == ("FFO per share for this quarter is held because the two readings of its earnings "
                                                            "release do not agree.")


def test_the_model_answer_reads_a_figure_written_as_printed():
    d = F.parse_ffo_json('{"ffo": null, "total": "1,278.9", "shares": "466,833", "quote": null}')
    assert d["total"] == 1278.9 and d["shares"] == 466833 and d["ffo"] is None
    assert F.parse_ffo_json('{"ffo": "$(0.35)"}')["ffo"] == -0.35


def test_a_q4_release_falls_back_to_the_quarter_end_it_prints_when_the_model_names_it():
    ex = [("r.htm", "For the Three Months Ended For the Twelve Months Ended December 31, 2025 December 31, 2024 FFO $ 1.01 $ 1.11")]
    assert F.quarter_end_fallback(ex, date(2026, 2, 4), "2025-12-31") == date(2025, 12, 31)
    assert F.quarter_end_fallback(ex, date(2026, 2, 4), "2025-09-30") is None               # the model names another quarter
    assert F.quarter_end_fallback([("r.htm", "no date here")], date(2026, 2, 4), "2025-12-31") is None
