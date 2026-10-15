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
