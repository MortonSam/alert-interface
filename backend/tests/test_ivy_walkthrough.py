"""Ivy's walkthrough: the 10-K readers, the margin measure, every quick-check template with worked examples, the step builders'
honest absences (the VMRK rule, the flags), the rival and featured rules, and the story sentences' output check. All pure."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

from app.services import fiscal_periods as F
from app.services import margins as M
from app.services import risk_factors as R
from app.services import segments as S
from app.services import walkthrough as W
from app.services import walkthrough_checks as C
from app.services import walkthrough_compare as WC
from app.services import walkthrough_data as W_D
from app.services import walkthrough_story as WS
from app.services import valuation as V


# ── segments ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _instance(facts: list[tuple[str, dict, float]], start="2025-09-28", end="2026-09-26") -> bytes:
    ctx, body = [], []
    for i, (tag, dims, val) in enumerate(facts):
        members = "".join(f'<xbrldi:explicitMember dimension="{a}">{m}</xbrldi:explicitMember>' for a, m in dims.items())
        seg = f"<xbrli:segment>{members}</xbrli:segment>" if members else ""
        ctx.append(f'<xbrli:context id="c{i}"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier>{seg}</xbrli:entity>'
                   f'<xbrli:period><xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>')
        body.append(f'<us-gaap:{tag} contextRef="c{i}" unitRef="usd" decimals="-6">{val}</us-gaap:{tag}>')
    return ('<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
            'xmlns:us-gaap="http://fasb.org/us-gaap/2025" xmlns:dei="http://xbrl.sec.gov/dei/2025">'
            f'<dei:DocumentPeriodEndDate contextRef="c0">{end}</dei:DocumentPeriodEndDate>' + "".join(ctx) + "".join(body) + "</xbrli:xbrl>").encode()


REV = "RevenueFromContractWithCustomerExcludingAssessedTax"
POS = "srt:ProductOrServiceAxis"
SEG = "us-gaap:StatementBusinessSegmentsAxis"
CONS = "srt:ConsolidationItemsAxis"


def test_apple_like_aggregate_beside_its_parts_reads_the_parts():
    facts = [(REV, {}, 400.0), (REV, {POS: "us-gaap:ProductMember"}, 300.0), (REV, {POS: "us-gaap:ServiceMember"}, 100.0),
             (REV, {POS: "aapl:IPhoneMember"}, 200.0), (REV, {POS: "aapl:MacMember"}, 60.0), (REV, {POS: "aapl:IPadMember"}, 40.0)]
    out = S.split_revenue(S.parse_instance(_instance(facts)), "Information Technology", {"aapl_IPhoneMember": "iPhone", "aapl_IPadMember": "iPad"})
    assert out["ok"] and out["axis_label"] == "product or service"
    assert [g["label"] for g in out["segments"]] == ["iPhone", "Service", "Mac", "iPad"]      # finest partition, generic Product dropped
    assert out["segments"][0]["share"] == 50.0


def test_business_segments_with_the_operating_segments_marker_and_corporate_rows():
    facts = [("RevenuesNetOfInterestExpense", {}, 182.0),
             ("RevenuesNetOfInterestExpense", {SEG: "jpm:CcbMember", CONS: "us-gaap:OperatingSegmentsMember"}, 76.0),
             ("RevenuesNetOfInterestExpense", {SEG: "jpm:CibMember", CONS: "us-gaap:OperatingSegmentsMember"}, 78.0),
             ("RevenuesNetOfInterestExpense", {SEG: "jpm:AwmMember", CONS: "us-gaap:OperatingSegmentsMember"}, 24.0),
             ("RevenuesNetOfInterestExpense", {CONS: "us-gaap:CorporateNonSegmentMember"}, 7.0),
             ("RevenuesNetOfInterestExpense", {CONS: "us-gaap:MaterialReconcilingItemsMember"}, -3.0)]
    out = S.split_revenue(S.parse_instance(_instance(facts)), "Financials")
    assert out["ok"] and out["axis_label"] == "business segment" and len(out["segments"]) == 3 and out["adjustments"] == 4.0


def test_a_split_that_does_not_add_up_is_an_absence_never_a_guess():
    facts = [(REV, {}, 100.0), (REV, {POS: "o:RetailMember"}, 75.0), (REV, {POS: "o:IndustrialMember"}, 15.0)]
    out = S.split_revenue(S.parse_instance(_instance(facts)), None)
    assert not out["ok"] and "do not add up" in out["reason"]


def test_acronym_labels_defer_to_a_readable_axis():
    facts = [(REV, {}, 100.0), (REV, {SEG: "mu:CmbuMember", CONS: "us-gaap:OperatingSegmentsMember"}, 60.0),
             (REV, {SEG: "mu:CdbuMember", CONS: "us-gaap:OperatingSegmentsMember"}, 40.0),
             (REV, {POS: "mu:DramMember"}, 76.0), (REV, {POS: "mu:NandMember"}, 24.0)]
    labels = {"mu_CmbuMember": "CMBU", "mu_CdbuMember": "CDBU", "mu_DramMember": "DRAM Products", "mu_NandMember": "NAND Products"}
    out = S.split_revenue(S.parse_instance(_instance(facts)), None, labels)
    assert [g["label"] for g in out["segments"]] == ["DRAM Products", "NAND Products"]


def test_labels_and_names():
    assert S.humanize("mu:ComputeAndNetworkingBusinessUnitMember") == "Compute and Networking Business Unit"
    assert S.label_for("tsla:AutomotiveSegmentMember", {}) == "Automotive"
    lab = (b'<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase" xmlns:xlink="http://www.w3.org/1999/xlink"><link:labelLink>'
           b'<link:loc xlink:label="loc1" xlink:href="x.xsd#mu_DramMember"/><link:labelArc xlink:from="loc1" xlink:to="lab1"/>'
           b'<link:label xlink:label="lab1" xlink:role="http://www.xbrl.org/2003/role/label">DRAM Products [Member]</link:label></link:labelLink></link:linkbase>')
    assert S.parse_labels(lab) == {"mu_DramMember": "DRAM Products"}


def test_partition_prefers_the_finest_exact_set():
    assert S.partition({"a": 50, "b": 30, "c": 20, "ab": 80}, 100) == ["a", "b", "c"]
    assert S.partition({"a": 50, "b": 30}, 100) is None


# ── risk factors ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_item_1a_is_the_long_section_and_headings_are_emphasised_sentences():
    body = "<p>" + "Text of the risk. " * 60 + "</p>"
    html = ("<html><body><div>Item 1A. Risk Factors</div><div>Item 1B. Unresolved Staff Comments</div>"
            "<p>See Item 1A, Risk Factors, for more.</p>"
            "<div><span style='font-weight:700'>Item 1A. Risk Factors</span></div>"
            "<div><b>Risks Related to Our Business</b></div>"
            "<div><span style='font-weight:700'>The following risk factors should be considered with the rest of this report.</span></div>"
            f"<div><span style='font-weight:700'>Prices for our products are volatile and may fall sharply.</span></div>{body}"
            f"<div><span style='font-style:italic'>We depend on a small number of customers for most sales.</span></div>{body}"
            f"<div><b>Competition could reduce our share of the market and our margins.</b></div>{body}"
            "<div>Item 1B. Unresolved Staff Comments</div></body></html>")
    out = R.read_html(html)
    assert out["ok"]
    assert [r["heading"] for r in out["risks"]] == ["Prices for our products are volatile and may fall sharply.",
                                                     "We depend on a small number of customers for most sales.",
                                                     "Competition could reduce our share of the market and our margins."]


def test_item_1_opening_is_kept_as_evidence_for_what_the_company_does():
    body = "<div>" + "Realty Income owns commercial properties under long-term net lease agreements with commercial clients. " * 30 + "</div>"
    html = ("<html><body><div>Item 1. Business</div><div>Item 1A. Risk Factors</div>"
            f"<div>Item 1. Business</div><div><b>Overview</b></div>{body}<div>12</div>"
            "<div>Item 1A. Risk Factors</div><div>" + "Risk text. " * 300 + "</div><div>Item 1B. Unresolved Staff Comments</div></body></html>")
    out = R.read_html(html)
    assert out["business"].startswith("Realty Income owns commercial properties") and len(out["business"]) <= R.BUSINESS_CHARS
    assert "Overview" not in out["business"] and "Risk text" not in out["business"]
    assert "From Item 1, Business, of its 10-K: Realty Income owns" in "\n".join(WS.fact_lines({"name": "O", "business": out["business"]}))


# ── margins ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _facts(tag_vals: dict[str, list[tuple[str, str, float]]]) -> dict:
    return {"facts": {"us-gaap": {t: {"units": {"USD": [{"start": s, "end": e, "val": v, "filed": e[:4] + "-12-31", "form": "10-Q"} for s, e, v in rows]}}
                                  for t, rows in tag_vals.items()}}}


QUARTERS = [("2022-07-01", "2022-09-30"), ("2022-10-01", "2022-12-31"), ("2023-01-01", "2023-03-31"), ("2023-04-01", "2023-06-30"), ("2023-07-01", "2023-09-30"), ("2023-10-01", "2023-12-31"),
            ("2024-01-01", "2024-03-31"), ("2024-04-01", "2024-06-30"), ("2024-07-01", "2024-09-30"), ("2024-10-01", "2024-12-31"),
            ("2025-01-01", "2025-03-31"), ("2025-04-01", "2025-06-30"), ("2025-07-01", "2025-09-30"), ("2025-10-01", "2025-12-31"),
            ("2026-01-01", "2026-03-31"), ("2026-04-01", "2026-06-30")]


def test_gross_margin_now_and_three_years_earlier_worked_example():
    rev = [(s, e, 100.0) for s, e in QUARTERS]
    gp = [(s, e, 40.0 if e < "2024" else 60.0) for s, e in QUARTERS]
    out = M.margins(_facts({REV: rev, "GrossProfit": gp}), "Information Technology", date(2026, 10, 19))
    assert out["ok"] and out["measure"] == "gross" and out["now"] == 60.0 and out["then"] == 40.0
    assert out["now_end"] == date(2026, 6, 30) and out["then_end"] == date(2023, 6, 30)


def test_no_gross_profit_filed_reads_operating_margin_and_reits_get_none():
    rev = [(s, e, 100.0) for s, e in QUARTERS]
    op = [(s, e, 5.0) for s, e in QUARTERS]
    out = M.margins(_facts({"Revenues": rev, "OperatingIncomeLoss": op, "CostOfGoodsAndServicesSold": [(s, e, 10.0) for s, e in QUARTERS]}), "Health Care", date(2026, 10, 19))
    assert out["measure"] == "operating" and out["now"] == 5.0           # never revenue less a partial cost tag (UNH)
    assert not M.margins({}, "Real Estate", date(2026, 10, 19))["ok"]
    banks = M.margins(_facts({"Revenues": rev, "NetIncomeLoss": [(s, e, 30.0) for s, e in QUARTERS]}), "Financials", date(2026, 10, 19))
    assert banks["measure"] == "net" and banks["now"] == 30.0


def test_a_tag_the_company_stopped_filing_is_not_now():
    old = [(s, e, 100.0) for s, e in QUARTERS[:8]]
    out = M.margins(_facts({REV: old, "GrossProfit": [(s, e, 50.0) for s, e in QUARTERS[:8]]}), None, date(2026, 10, 19))
    assert not out["ok"]


# ── fiscal quarter names (DEI DocumentFiscalPeriodFocus / DocumentFiscalYearFocus) ───────────────────────────────────────────

def _fy_facts(rows: list[tuple[str, str, str, int, str, str]]) -> dict:
    """Company facts with one revenue fact per filing: (accn, start, end, fy, fp, form)."""
    return {"facts": {"us-gaap": {REV: {"units": {"USD": [{"accn": a, "start": s, "end": e, "fy": fy, "fp": fp, "form": form, "val": 1}
                                                          for a, s, e, fy, fp, form in rows]}}}}}


# Micron: a 52/53-week year ending around the start of September (fiscal 2026 ended Sep 3, 2026, a 53-week year)
MU_PERIODS = F.period_map(_fy_facts([("a1", "2025-08-29", "2025-11-27", 2026, "Q1", "10-Q"), ("a2", "2025-11-28", "2026-02-26", 2026, "Q2", "10-Q"),
                                     ("a3", "2026-02-27", "2026-05-28", 2026, "Q3", "10-Q"), ("a4", "2025-08-29", "2026-09-03", 2026, "FY", "10-K"),
                                     ("a0", "2022-09-02", "2023-08-31", 2023, "FY", "10-K")]))
JPM_PERIODS = F.period_map(_fy_facts([("b1", "2026-04-01", "2026-06-30", 2026, "Q2", "10-Q"), ("b2", "2025-01-01", "2025-12-31", 2025, "FY", "10-K"),
                                      ("b3", "2025-07-01", "2025-09-30", 2025, "Q3", "10-Q")]))


def test_period_map_reads_each_filing_once_and_the_10k_is_q4():
    assert MU_PERIODS["2026-09-03"] == [2026, "Q4"] and MU_PERIODS["2025-11-27"] == [2026, "Q1"]
    two = _fy_facts([("x", "2026-01-01", "2026-03-31", 2026, "Q1", "10-Q"), ("x", "2026-01-01", "2026-03-31", 2025, "Q4", "10-Q")])
    assert F.period_map(two) == {}                                            # a filing naming two periods names none
    dell = _fy_facts([("e1", "2023-02-04", "2023-05-05", 2024, "FY", "10-Q"), ("e2", "2023-05-06", "2023-08-04", 2024, "FY", "10-Q"),
                      ("e3", "2023-08-05", "2023-11-03", 2024, "Q3", "10-Q")])
    assert F.period_map(dell) == {"2023-11-03": [2024, "Q3"]}                 # Dell's 2023 10-Qs say "FY": no fiscal name, never Q4
    assert F.through(F.period_map(dell), date(2023, 8, 4)) == "through the quarter ended Aug 4, 2023"
    dup = _fy_facts([("f1", "2023-01-01", "2023-03-31", 2023, "Q1", "10-Q"), ("f2", "2023-04-01", "2023-06-30", 2023, "Q1", "10-Q")])
    assert F.period_map(dup) == {}                                            # a name two quarters claim names neither


def test_a_september_fiscal_year_end_reads_fiscal_quarters():
    assert F.quarter_label(MU_PERIODS, date(2026, 9, 3)) == "Fiscal Q4 2026, ended Sep 3, 2026"
    assert F.four_label(MU_PERIODS, date(2026, 9, 3)) == "Last four quarters, through fiscal Q4 2026"
    assert F.quarter(MU_PERIODS, date(2025, 11, 27)) == "fiscal Q1 2026, ended Nov 27, 2025"
    assert F.year(MU_PERIODS, date(2026, 9, 3)) == "fiscal 2026, ended Sep 3, 2026"
    assert F.through(MU_PERIODS, date(2023, 8, 31)) == "through fiscal Q4 2023"


def test_a_calendar_year_reads_plain_quarters():
    assert F.quarter_label(JPM_PERIODS, date(2026, 6, 30)) == "Q2 2026, ended Jun 30, 2026"
    assert F.four_label(JPM_PERIODS, date(2026, 6, 30)) == "Last four quarters, through Q2 2026"
    assert F.year(JPM_PERIODS, date(2025, 12, 31)) == "the year ended Dec 31, 2025"


def test_a_52_53_week_year():
    intc = F.period_map(_fy_facts([("c1", "2026-06-28", "2026-09-26", 2026, "Q3", "10-Q"), ("c2", "2024-12-29", "2025-12-27", 2025, "FY", "10-K"),
                                   ("c3", "2026-12-27", "2027-01-02", 2026, "FY", "10-K")]))
    assert F.quarter_label(intc, date(2026, 9, 26)) == "Q3 2026, ended Sep 26, 2026"          # ends near the calendar's: no "fiscal"
    assert F.quarter_label(intc, date(2025, 12, 27)) == "Q4 2025, ended Dec 27, 2025"
    assert F.quarter_label(intc, date(2027, 1, 2)) == "Q4 2026, ended Jan 2, 2027"             # a 53rd week into January stays Q4 2026
    wmt = F.period_map(_fy_facts([("d1", "2025-08-02", "2025-10-31", 2026, "Q3", "10-Q")]))
    assert F.quarter_label(wmt, date(2025, 10, 31)) == "Fiscal Q3 2026, ended Oct 31, 2025"   # a year ending in January
    assert F.quarter_label(intc, date(2026, 9, 28)) == "Q3 2026, ended Sep 28, 2026"           # a stored end two days off takes the filing's name
    assert F.quarter_label({}, date(2026, 9, 3)) == "Quarter ended Sep 3, 2026"               # no filing names it: never a guess


def test_quarter_to_never_appears():
    rows = [{"metric": "revenue", "period_end": date(2025, 11, 27) + timedelta(days=91 * i), "value": 100 + i, "year_ago_value": 50, "growth_pct": 50.0 + i,
             "phrase": "up", "held_reason": None, "readers": "XBRL / XBRL"} for i in range(4)]
    s = W.step_growth("Micron", rows, "Information Technology", True, MU_PERIODS)
    text = json.dumps(s)
    assert "Quarter to" not in text and "quarter to" not in text and "Four quarters to" not in text
    assert s["numbers"][1]["as_of"].startswith("Last four quarters, through")


# ── quick checks: worked examples for every template ──────────────────────────────────────────────────────────────────────
# The reviewer's rule (2026-10-19): every check states one fact about this stock and asks what it means; the right option follows
# the data's direction and the wrong ones are clearly wrong to someone who understood the idea.

def test_step1_has_no_check_and_its_text_never_states_the_dependence_reading():
    seg = {"ok": True, "filed": date(2026, 10, 9), "end": date(2026, 9, 3), "total": 133.2e9, "url": "u",
           "segments": [{"label": "DRAM Products", "value": 100.7e9, "share": 75.6}, {"label": "NAND Products", "value": 31.8e9, "share": 23.9}]}
    s = W.step_business("Micron", {"short_description": "Micron makes memory."}, seg, None, MU_PERIODS)
    assert s["check"] is None and s["described"]
    text = " ".join(s["sentences"]).lower()
    assert "one line" not in text and "most of" not in text and "depend" not in text


def test_growth_check_asks_what_earnings_per_share_against_sales_means():
    c = C.growth_check("Micron", 379.3, "fiscal Q4 2026", 1061.5)
    assert c["question"] == "Micron's earnings per share grew faster than its sales in fiscal Q4 2026. What does that usually mean?"
    assert c["options"][c["answer"]] == "Each sale earns more profit than a year ago"
    assert set(c["options"]) == {"Each sale earns more profit than a year ago", "It is selling more but earning less on each sale", "Its sales and profit always grow together"}
    assert "buybacks" in c["why"] and "1,061.5%" in c["why"]
    c = C.growth_check("X", 10.0, "Q2 2026", -3.7)
    assert c["options"][c["answer"]] == "It is selling more but earning less on each sale" and c["question"].startswith("X's earnings per share fell while its sales rose")
    assert C.growth_check("X", 10.0, "Q2 2026", 10.4) is None                 # factors 1.104 / 1.10: within 5%, about as fast, no question
    assert C.growth_check("X", 9.7, "Q2 2026", None) is None                  # no per-share figure, no question
    assert C.growth_check("X", -5.0, "Q2 2026", -20.0) is None                # slower while sales fell: "selling more" would be false
    c = C.growth_check("JPMorgan Chase", 27.7, "Q2 2026", 46.9, noun="revenue")
    assert c["options"][c["answer"]] == "Each dollar of revenue earns more profit than a year ago" and "sales" not in json.dumps(c)
    c = C.growth_check("Realty Income", 9.7, "Q2 2026", 3.8, "FFO per share")
    assert "FFO per share grew slower" in c["question"] and "FFO per share" in c["why"]
    assert C.growth_check("Micron", 379.3, "q", 1061.5) == C.growth_check("Micron", 379.3, "q", 1061.5)      # a fixed order per stock
    assert len({C.growth_check(n, 10.0, "q", 30.0)["answer"] for n in ("Apple", "Micron", "NVIDIA", "Tesla", "JPMorgan Chase", "Realty Income")}) > 1


def test_margins_check_reads_the_whole_cents_shown():
    c = C.margins_check("Micron", 80.7, -9.1)
    assert c["options"][c["answer"]] == "Pricing power or lower costs" and "lost 9¢ on each sales dollar three years earlier" in c["question"]
    assert "from a loss of 9¢ to 81¢" in c["why"] and "90¢ more" in c["why"] and "cyclical" in c["why"]
    c = C.margins_check("Tesla", 18.9, 21.5)                                   # shown as 22¢ and 19¢: 3¢, never "2.6 points"
    assert c["answer"] == 1 and "from 22¢ to 19¢" in c["why"] and "3¢ less" in c["why"] and "2.6" not in c["why"]
    c = C.margins_check("JPM", 32.6, 32.6, "revenue dollar")
    assert c["answer"] == 2 and "33¢" in c["why"]
    assert C.margins_check("X", 40.0, None) is None


def test_market_check_picks_the_closer_benchmark():
    assert C.year_owner(358.4, 20.1, 16.0) == "company"                      # Micron: far from both
    assert C.year_owner(-0.5, 2.3, 16.0) == "industry"                       # Realty Income: 2.8 points from its sector, 16.5 from the market
    assert C.year_owner(13.3, 7.0, 16.0) == "market"                         # JPM: only the S&P 500 is close
    assert C.year_owner(19.4, 20.1, 16.0) == "industry"                      # NVIDIA: close to both, closer to its sector
    assert C.year_owner(10.0, 12.0, 8.0) == "market"                         # a tie goes to the market
    assert C.close(100.0, 120.0) and not C.close(100.0, 126.0)               # a fifth of the larger move once that is wider than 5 points
    c = C.market_check("NVIDIA", "Information Technology", 19.4, 20.1, 16.0)
    assert c["options"] == ["The company", "Its industry", "The whole market"] and c["answer"] == 1
    assert "close to both, and closer to the typical Information Technology stock's than to the S&P 500's" in c["why"]
    c = C.market_check("Micron", "Information Technology", 358.4, 20.1, 16.0)
    assert c["answer"] == 0 and c["question"] == ("Over the year Micron rose 358.4%, the typical Information Technology stock rose 20.1% and the S&P 500 rose 16.0%. "
                                                  "Was Micron's year mostly the company, its industry, or the whole market?")
    assert "within 5 points" in c["why"] and "picks the closer one" in c["why"]


def test_move_owner_for_one_day():
    assert C.move_owner(18.4, 1.7, 1.0) == "company" and C.move_owner(-3.0, -2.0, 1.0) == "market"
    assert C.move_owner(-3.0, 2.0, 1.0) == "company" and C.move_owner(1.2, 0.8, 1.0) == "company" and C.move_owner(5.0, None, 1.0) == "company"


def test_pe_check_asks_for_a_common_reason():
    c = C.pe_check("Micron", 11.8, 16.7)
    assert c["question"] == "Investors are paying less for each dollar of Micron's profit than they usually do. What is a common reason?"
    assert c["options"][c["answer"]] == "They expect its profits to fall from here" and "Its stock split" in c["options"]
    assert "below its five-year median of 16.7" in c["why"] and "split" in c["why"]
    c = C.pe_check("Apple", 39.4, 34.3)
    assert c["options"][c["answer"]] == "They expect its profits to keep growing" and "paying more" in c["question"]
    assert C.pe_check("JPMorgan Chase", 14.2, 14.4) is None                    # about usual: no question


def test_report_check_states_the_multiple_and_asks_what_it_means_for_a_holder():
    c = C.report_check("JPMorgan Chase", 2.9, 1.1, "its next report on Jan 14, 2027")
    assert c["question"] == ("Report days move JPMorgan Chase about 2.6 times as much as an ordinary day. "
                             "What does that mean for someone holding it through its next report on Jan 14, 2027?")
    assert c["options"][c["answer"]] == "Expect a bigger swing that day, in either direction"
    assert set(c["options"]) == {C.REPORT_RIGHT, *C.REPORT_WRONG} and "±2.9%" in c["why"] and "±1.1%" in c["why"]
    assert C.report_check("X", 1.4, 1.0, "its next report") is None           # under 1.5 times: no question
    assert C.report_check("X", 5.0, None, "its next report") is None


def test_step6_asks_through_the_next_report_and_never_states_the_ordinary_move():
    from types import SimpleNamespace
    ne = SimpleNamespace(date=date(2026, 12, 15), confirmation="estimated", window_start=None, window_end=None, note=None)
    s = W.step_upcoming("Micron", ne, None, None, {"pct": 6.8, "n": 21, "as_of": date(2026, 9, 30)}, date(2026, 10, 28), 2.1)
    assert s["check"]["question"].endswith("holding it through its next report, expected around Dec 15, 2026?")
    assert "2.1" not in " ".join(s["sentences"] + [n["value"] for n in s["numbers"] + s["deeper"]])
    conf = SimpleNamespace(date=date(2027, 1, 14), confirmation="confirmed", window_start=None, window_end=None, note=None)
    s = W.step_upcoming("JPM", conf, None, None, {"pct": 2.9, "n": 20, "as_of": date(2026, 7, 14)}, None, 1.1)
    assert "through its next report on Jan 14, 2027?" in s["check"]["question"]


def test_risk_mapping_is_unambiguous_and_skips_supply_chain():
    assert C.risk_target("Volatility in average selling prices for our products") == "margins"
    assert C.risk_target("We face intense competition in the semiconductor memory market") == "margins"
    assert C.risk_target("A significant portion of our revenue is from a limited number of customers") == "growth"
    assert C.risk_target("Changes in demand and orders could hurt us") == "growth"
    assert C.risk_target("Our tenants may not renew their leases") == "growth"
    assert C.risk_target("Competition could reduce demand for our products") is None          # both: ambiguous
    assert C.risk_target("We depend on suppliers, and their prices may rise") is None          # supply chain: no check
    assert C.risk_target("Supply and customer demand can end up out of step") is None
    assert C.risk_target("Oversupply lowers memory prices") == "margins"
    assert C.risk_target("Cybersecurity incidents could disrupt our business") is None
    for step, rx in C.RISK_TARGETS:                                           # the explanation's words are the patterns' words
        for w in re.split(r", | or ", C.RISK_WORDS[step]):
            assert rx.search(w), w


def _risk_steps():
    steps = [W._step(n, status="ok", idea=None) for n in range(1, 8)]
    pts = {2: "The 379.3% rise in its sales in fiscal Q4 2026", 3: "The 81¢ it keeps of each sales dollar", 4: "The 358.4% rise in its stock over the year",
           5: "Its P/E of 11.8", 1: "The 75.6% of its sales from DRAM Products", 6: "Its typical ±6.8% move on a report day"}
    for st in steps:
        st["point"] = pts.get(st["n"])
    return steps, pts


def test_risk_check_offers_business_results_only():
    steps, pts = _risk_steps()
    risks = [{"n": 1, "sentence": "Selling prices for its chips have swung sharply."}, {"n": 2, "sentence": "A few customers bring in most of its money."}]
    c = W.risk_check("Micron", risks, {1: "Volatility in average selling prices", 2: "Customer concentration"}, steps)
    assert c["options"][c["answer"]] == pts[3] and set(c["options"]) == {pts[1], pts[2], pts[3]}
    assert c["question"] == ("Micron lists this risk. Selling prices for its chips have swung sharply. If it came true, which of Micron's own results "
                             "would it hit most directly?")
    assert not {pts[4], pts[5]} & set(c["options"])                          # never the stock price or the P/E
    c = W.risk_check("Micron", risks[1:], {2: "Customer concentration"}, steps)
    assert c["options"][c["answer"]] == pts[2]
    giveaway = [{"n": 1, "sentence": "Falling prices would squeeze its margins."}]       # names its own answer: never the question
    assert W.risk_check("Micron", giveaway, {1: "Pricing pressure"}, steps) is None
    assert W.risk_check("Micron", [{"n": 9, "sentence": "Hackers could break in."}], {9: "Cybersecurity"}, steps) is None      # no fallback question
    steps[0]["status"] = "absent"
    assert W.risk_check("Micron", risks, {1: "Volatility in average selling prices"}, steps) is None   # three business results or no check


def test_every_check_is_free_of_colons_em_dashes_and_plus_signs():
    checks = [C.growth_check("A", 3, "p", 15), C.growth_check("A", 3, "p", -9), C.margins_check("A", 40, 10), C.margins_check("A", -5, 2),
              C.market_check("A", "Energy", 3, 2, 1), C.pe_check("A", 10, 12), C.pe_check("A", 14, 12),
              C.report_check("A", 5, 1.5, "its next report"), C.risk_check("A", "B.", "C", ["D", "E"])]
    for c in checks:
        text = " ".join([c["question"], c["why"], *c["options"]])
        assert ":" not in text and "—" not in text and "+" not in text, text
        assert not re.search(r"(?<![\w-])-\d", text), text
        assert not any(re.fullmatch(r"About \d+ times?", o) for o in c["options"])       # no numeric guesses


def test_no_idea_text_states_a_checks_answer():
    answers = [*C.GROWTH_RIGHT.values(), *C.PE_RIGHT.values(), C.REPORT_RIGHT, "pricing power", "competition or rising costs", "expect profits to grow",
               "jump or drop"]
    for title, text in W.IDEAS.values():
        for a in answers:
            assert a.lower() not in text.lower(), (title, a)


# ── step builders ───────────────────────────────────────────────────────────────────────────────────────────────────────────

MERGER = {"name": "AvalonBay Communities, Inc.", "date": date(2026, 8, 17)}


def test_the_vmrk_rule_a_profile_and_10k_before_a_merger_are_never_used():
    profile = {"short_description": "Equity Residential is committed to creating communities.", "latest_filing_date": date(2026, 7, 30)}
    seg = {"ok": True, "filed": date(2026, 2, 13), "segments": [], "total": 1.0, "end": date(2025, 12, 31)}
    s = W.step_business("Vivmark Residential", profile, seg, MERGER)
    assert s["status"] == "absent" and "merged with AvalonBay Communities on Aug 17, 2026" in s["absent"] and "Equity Residential" not in s["absent"]
    risks = W.step_risks("Vivmark Residential", {"ok": True, "filed": date(2026, 2, 13), "risks": []}, MERGER)
    assert risks["status"] == "absent"


def test_negative_margin_reads_as_a_loss_and_a_number():
    m = {"ok": True, "measure": "gross", "label": "gross margin", "plain": "after paying for what it sold", "now": 80.7, "then": -9.1,
         "now_start": date(2025, 9, 1), "now_end": date(2026, 9, 3), "then_end": date(2023, 8, 31), "revenue_tag": REV, "profit_tag": "GrossProfit",
         "now_revenue": 1.0, "now_profit": 1.0, "then_revenue": 1.0, "then_profit": 1.0}
    s = W.step_margins("Micron", m, [])
    assert [n["value"] for n in s["numbers"]] == ["81¢", "−9¢"]
    assert s["sentences"][0] == "Micron keeps 81¢ of each sales dollar after paying for what it sold, against a loss of 9¢ three years earlier."
    assert s["idea"]["concept"] == "margins"
    held = W.step_margins("Micron", m, [{"kind": "merger", "date": date(2026, 1, 5), "name": "Other Co"}])
    assert held["status"] == "absent"


def test_ttm_growth_needs_four_consecutive_agreed_quarters():
    rows = [{"period_end": date(2025, 9, 30), "value": 110, "year_ago_value": 100}, {"period_end": date(2025, 12, 31), "value": 110, "year_ago_value": 100},
            {"period_end": date(2026, 3, 31), "value": 110, "year_ago_value": 100}, {"period_end": date(2026, 6, 30), "value": 110, "year_ago_value": 100}]
    assert W.ttm_growth(rows)[2] == 10.0
    assert W.ttm_growth(rows[:3]) is None
    assert W.ttm_growth(rows[:3] + [{**rows[3], "held_reason": "Merged"}]) is None


def test_flags_gate_growth_and_pe_at_serve_time():
    from app.routers.walkthrough import gate
    steps = [W._step(n, status="ok", idea=None, summary=f"line {n}") for n in range(1, 8)]
    payload = {"name": "Micron", "sector": "Information Technology", "steps": steps,
               "compare": {"rows": {"growth": {"ttm": {"value": "+1%"}}, "valuation": {"pe": {"value": "11.8"}}}}}
    out = gate(payload, growth_on=False, pe_on=False)
    assert out["steps"][1]["status"] == "absent" and W.GROWTH_IN_REVIEW in out["steps"][1]["absent"]
    assert out["steps"][4]["status"] == "absent" and W.PE_IN_REVIEW in out["steps"][4]["absent"]
    assert out["compare"]["rows"]["growth"] == {} and out["compare"]["rows"]["valuation"] == {}
    assert out["entry"]                                                      # five of seven steps still show data
    assert 2 not in [k["n"] for k in out["summary"]["known"]] and payload["steps"][1]["status"] == "ok"      # the stored payload is untouched
    assert "Whether its sales are growing (figures still being checked)" in out["summary"]["uncertain"]
    assert gate(payload, True, True)["steps"][1]["status"] == "ok"
    reit = {**payload, "reit": True}
    assert gate(reit, True, False)["steps"][4]["status"] == "ok"             # a trust's price to FFO is not a P/E: PE_ENABLED leaves it
    thin = {**payload, "steps": [W._step(n, status="ok" if n in (4, 6, 7) else "absent", idea=None) for n in range(1, 8)]}
    assert not gate(thin, True, True)["entry"]                               # three of seven: the ticker page offers no walkthrough (VMRK)
    assert W.ENTRY_MIN_STEPS == 4


def test_pe_series_median_is_the_stored_median():
    quarters = [{"start": date(2020, 1, 1) + (date(2020, 4, 1) - date(2020, 1, 1)) * i, "end": date(2020, 3, 31) + (date(2020, 6, 30) - date(2020, 3, 31)) * i,
                 "eps": 1.0 + 0.1 * i, "filed": date(2020, 5, 1) + (date(2020, 8, 1) - date(2020, 5, 1)) * i, "derived": False} for i in range(20)]
    bars = [(date(2021, 6, 1) + (date(2021, 6, 2) - date(2021, 6, 1)) * k, 50.0 + k % 30) for k in range(1000)]
    from statistics import median
    series = V.pe_series_clean(bars, quarters, [])
    assert round(median(v for _, v in series), 1) == V.pe_history_clean(bars, quarters, 20.0, [])["median"]


def test_summary_lists_takeaways_and_this_stocks_real_gaps():
    steps = [W._step(1, status="ok", idea="segments", summary="A."), W._step(2, status="absent", idea="growth", absent="x", gap="its filings and earnings releases don't agree yet"),
             W._step(3, status="ok", idea="margins", summary="C.")] + [W._step(n, status="absent", idea=None, gap="why") for n in range(4, 6)]
    from types import SimpleNamespace
    ne = SimpleNamespace(date=date(2026, 12, 15), confirmation="estimated", window_start=None, window_end=None, note=None)
    steps += [W.step_upcoming("Micron", ne, None, None, None, None), W._step(7, status="absent", idea=None, gap="its risk section couldn't be found")]
    s = W.summary("Micron", steps)
    assert [k["n"] for k in s["known"]] == [1, 3, 6]
    assert s["uncertain"] == ["Whether its sales are growing (its filings and earnings releases don't agree yet)", "How its stock did against the market (why)",
                              "How it is valued (why)", "What could go wrong (its risk section couldn't be found)",
                              "What its next report shows, due around Dec 15, 2026, a date the company hasn't confirmed."]
    assert [c["concept"] for c in s["concepts"]] == ["segments", "margins", "report_move"] and s["closing"] == W.CLOSING_LINE
    generic = ("Whether growth this fast lasts.", "Where the cycle in its prices turns next.", "Whether any of the risks it names comes to pass.")
    assert not set(generic) & set(s["uncertain"])


# ── rules: rival, ruler, featured ───────────────────────────────────────────────────────────────────────────────────────────

TICKERS = {"MU": {"symbol": "MU", "industry": "Semiconductors", "sector": "IT", "market_cap": 1.0e12, "index_member": True},
           "AVGO": {"symbol": "AVGO", "industry": "Semiconductors", "sector": "IT", "market_cap": 1.5e12, "index_member": True},
           "AMD": {"symbol": "AMD", "industry": "Semiconductors", "sector": "IT", "market_cap": 0.6e12, "index_member": True},
           "NVDA": {"symbol": "NVDA", "industry": "Semiconductors", "sector": "IT", "market_cap": 5.0e12, "index_member": True},
           "ORCL": {"symbol": "ORCL", "industry": "Software", "sector": "IT", "market_cap": 0.9e12, "index_member": True}}


def test_rival_is_the_closest_value_by_ratio_in_the_sub_industry():
    have = set(TICKERS)
    assert WC.rival_for("MU", TICKERS, have) == {"symbol": "AVGO", "basis": "sub-industry"}    # 1.5x beats AMD's 1/0.6 = 1.67x
    assert WC.rival_for("ORCL", TICKERS, have) == {"symbol": "MU", "basis": "sector"}          # no other software stock: the sector
    assert WC.ruler_for("MU") == "AAPL" and WC.ruler_for("AAPL") == "MSFT"


def test_featured_rule():
    today = date(2026, 10, 19)
    cands = [{"symbol": "AAPL", "market_cap": 5e12, "full": True, "next_date": date(2026, 10, 29), "confirmed": True},
             {"symbol": "NVDA", "market_cap": 6e12, "full": True, "next_date": date(2026, 11, 19), "confirmed": True},
             {"symbol": "MSFT", "market_cap": 4e12, "full": False, "next_date": date(2026, 10, 22), "confirmed": True}]
    assert WC.choose_featured(cands, today, [])["symbol"] == "AAPL"            # reports within 14 days, full; MSFT is not full
    later = [{**c, "next_date": None} for c in cands]
    assert WC.choose_featured(later, today, [])["symbol"] == "NVDA"
    assert WC.choose_featured(later, today, [{"symbol": "NVDA", "date": "2026-10-10"}])["symbol"] == "AAPL"


# ── story sentences ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_story_output_check_rejects_numbers_verdicts_and_punctuation():
    ok = "Memory chips go into most electronics, so prices for them shape Micron's results."
    assert WS.output_problems(ok, WS.STORY_WORDS) == []
    assert WS.output_problems("Sales rose 40% last year.", WS.STORY_WORDS)
    assert WS.output_problems("The stock looks cheap after the drop.", WS.STORY_WORDS)
    assert WS.output_problems("Prices swing: a lot.", WS.STORY_WORDS)
    assert WS.output_problems("It sells twice as much as before.", WS.STORY_WORDS)
    assert WS.output_problems("Margins are high, likely because its chips are hard to replace.", WS.STORY_WORDS)
    assert WS.output_problems("Its region is not described in the information shown here.", WS.STORY_WORDS)
    assert WS.output_problems("Much of its revenue comes from the data center market.", WS.STORY_WORDS) == []
    assert WS.output_problems("Apple sells phones while there is no available description of what Vivmark does.", WS.STORY_WORDS)
    assert WS.output_problems("Vivmark operates in a manner that has not been described here.", WS.STORY_WORDS)


def test_parse_draft_and_items_drop_unknown_risks():
    d = WS.parse_draft('noise {"business": "A b.", "risks": [{"n": 2, "sentence": "R two."}, {"n": 99, "sentence": "Made up."}, {"n": 2, "sentence": "Again."}]} end')
    assert WS.items(d, {1, 2, 3}) == [("business", "A b."), ("risk:2", "R two.")]


def test_apply_puts_verified_sentences_on_their_steps():
    payload = {"name": "Micron", "steps": [W._step(n, status="ok" if n != 7 else "partial", idea=None) for n in range(1, 8)]}
    payload["steps"][6]["source"] = {"label": "Item 1A of its 10-K, filed Oct 9, 2026", "url": "u"}
    payload["steps"][0]["summary"] = "Its biggest line, DRAM Products, brought in 75.6% of its sales in fiscal 2026, ended Sep 3, 2026."
    payload["steps"][0]["fact"] = {"concept": "segments"}
    for st, pt in zip(payload["steps"], ["A", "B", "The 81¢ it keeps of each sales dollar", "C", "D", "E", None]):
        st["point"] = pt
    WS.apply(payload, {"sentences": {"business": "Story.", "does": "Micron makes memory chips.", "risk:4": "Rivals cut prices."}}, {4: "Intense competition"})
    assert payload["steps"][0]["story"] == "Story." and payload["steps"][1]["story"] is None
    assert payload["summary"]["known"][0]["line"] == "Micron makes memory chips. Its biggest line, DRAM Products, brought in 75.6% of its sales in fiscal 2026, ended Sep 3, 2026."
    p2 = {"name": "JPMorgan Chase", "steps": [W._step(n, status="ok", idea=None) for n in range(1, 8)]}
    p2["steps"][0].update(sentences=["Vendor text naming Commercial Banking.", "Its biggest line is X."], described=True)
    p2["steps"][6]["status"] = "absent"
    WS.apply(p2, {"sentences": {"does": "JPMorgan Chase takes deposits and makes loans."}})
    assert p2["steps"][0]["sentences"] == ["JPMorgan Chase takes deposits and makes loans.", "Its biggest line is X."]
    assert payload["steps"][6]["status"] == "ok" and payload["steps"][6]["risks"] == [{"n": 4, "sentence": "Rivals cut prices."}]
    c = payload["steps"][6]["check"]
    assert c["concept"] == "risk_factors" and c["options"][c["answer"]] == "The 81¢ it keeps of each sales dollar"


def test_growth_falls_back_to_the_newest_agreed_quarter_and_never_prints_iso_dates():
    rows = [{"metric": "revenue", "period_end": date(2026, 3, 31), "value": 110, "year_ago_value": 100, "growth_pct": 10.0, "phrase": "up 10.0% from a year earlier",
             "held_reason": None, "readers": "XBRL and the earnings release / XBRL and the earnings release"},
            {"metric": "revenue", "period_end": date(2026, 6, 30), "value": None, "year_ago_value": None, "growth_pct": None, "phrase": None, "held_reason": None, "readers": None}]
    s = W.step_growth("Micron", rows, "Information Technology", True)
    assert s["status"] == "partial" and s["numbers"][0]["as_of"] == "Quarter ended Mar 31, 2026"
    assert W.step_growth("JPM", rows, "Financials", True, {"2026-03-31": [2026, "Q1"]})["numbers"][0]["as_of"] == "Q1 2026, ended Mar 31, 2026"
    held = W.step_growth("Micron", [{**rows[0], "period_end": date(2026, 6, 30), "held_reason": "Spun off Qnity on 2025-11-01, inside the year compared"}], None, True)
    assert held["absent"] == "Ivy can't show this for Micron yet. Spun off Qnity on Nov 1, 2025, inside the year compared."


def test_nightly_cost_guards_compare_sentences_and_margins_change_only_with_filings():
    from app.scripts.build_walkthroughs import latest_periodic
    cell = lambda v: {"value": v, "as_of": "a"}
    side = lambda **rows: {"name": "X", "compare": {"rows": {"sells": {"share": cell("DRAM")}, **rows}}, "steps": [{"key": "business", "status": "ok"}]}
    a, b = side(stock_1y={"close": cell("+1%")}, valuation={"pe": cell("11.8")}), side()
    assert WS.compare_fingerprint(a, b) == WS.compare_fingerprint(side(stock_1y={"close": cell("+9%")}, valuation={"pe": cell("12.4")}), b)   # prices move nightly
    assert WS.compare_fingerprint(a, b) != WS.compare_fingerprint(side(sells={"share": cell("NAND")}), b)
    subs = {"filings": {"recent": {"form": ["8-K", "10-Q", "10-K"], "accessionNumber": ["a1", "a2", "a3"]}}}
    assert latest_periodic(subs) == "a2"


def test_the_walkthrough_is_hidden_until_its_flag_or_the_admin_token():
    import pytest
    from fastapi import HTTPException
    from app.config import settings
    from app.routers.walkthrough import _shown
    old = settings.ivy_walkthrough_enabled
    try:
        settings.ivy_walkthrough_enabled = False
        with pytest.raises(HTTPException):
            _shown(admin=False)
        _shown(admin=True)
        settings.ivy_walkthrough_enabled = True
        _shown(admin=False)
    finally:
        settings.ivy_walkthrough_enabled = old


# ── numbers and signs ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_figures_carry_separators_and_true_minus_signs_and_sentences_use_words():
    assert C.signed(1061.5) == "+1,061.5%" and C.signed(-0.4) == "−0.4%" and C.pct(-1061.5) == "1,061.5%" and C.num(-9.04) == "−9.0"
    assert C.moved(1.6) == "rose 1.6%" and C.moved(-0.4) == "fell 0.4%"
    assert C.change_noun(3.1) == "a 3.1% rise" and C.change_noun(8.2) == "an 8.2% rise" and C.change_noun(-11.0) == "an 11.0% fall" and C.change_noun(-1.2) == "a 1.2% fall"
    assert W.money_words(-1.4e9) == "−$1.4 billion" and W.dollars(-0.12) == "−$0.12" and W.cents_value(-9.1) == "−9¢"
    assert W.change_phrase(1061.5, "up 1061.5% from a year earlier") == "up 1,061.5% from a year earlier"
    assert W.change_phrase(None, "swung to a profit") == "swung to a profit"
    rows = [{"metric": "revenue", "period_end": date(2026, 9, 3), "value": 54.2e9, "year_ago_value": 11.3e9, "growth_pct": 379.3, "phrase": "up 379.3% from a year earlier",
             "held_reason": None, "readers": "XBRL"},
            {"metric": "eps", "period_end": date(2026, 9, 3), "value": 32.87, "year_ago_value": 2.83, "growth_pct": 1061.5, "phrase": "up 1061.5% from a year earlier", "held_reason": None}]
    s = W.step_growth("Micron", rows, "Information Technology", True, MU_PERIODS)
    assert s["sentences"][-1] == "Earnings per share were $32.87 in that quarter, up 1,061.5% from a year earlier."
    for t in s["sentences"]:
        assert "+" not in t


def test_validate_flags_unformatted_figures():
    from app.scripts.validate_data import WALK_HYPHEN_MINUS, WALK_NO_SEPARATOR, visible_text
    assert WALK_HYPHEN_MINUS.search("fell -9.0%") and not WALK_HYPHEN_MINUS.search("fell −9.0%") and not WALK_HYPHEN_MINUS.search("year-ago 5")
    assert WALK_NO_SEPARATOR.search("up 1061.5%") and not WALK_NO_SEPARATOR.search("up 1,061.5% in 2026") and WALK_NO_SEPARATOR.search("$1234")
    p = {"steps": [W._step(4, status="ok", idea=None, sentences=["It rose 1.6%."], numbers=[{"label": "a", "value": "+1.6%", "as_of": "Close Oct 16, 2026"}])], "compare": {"rows": {}}}
    assert "It rose 1.6%." in visible_text(p) and "+1.6%" in visible_text(p)


# ── real estate trusts ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_reit_is_never_taught_pe():
    assert W.is_reit("Real Estate", "Retail REITs") and not W.is_reit("Real Estate", "Real Estate Services") and not W.is_reit("Financials", "Diversified Banks")
    s = W.step_valuation_reit("Realty Income", None, {"date": date(2026, 10, 16), "close": 57.0})
    assert s["status"] == "absent" and s["idea"]["concept"] == "p_ffo" and "FFO" in s["absent"] and "P/E" not in s["absent"]
    assert "P/E" not in W.IDEAS["p_ffo"][1]
    ffo = W_D.ffo_view([(date(2025, 6, 30), 1.05), (date(2025, 9, 30), 1.06), (date(2025, 12, 31), 1.06), (date(2026, 3, 31), 1.06), (date(2026, 6, 30), 1.09)])
    assert ffo["latest"]["growth_pct"] == 3.8 and ffo["ttm"]["sum"] == 4.27
    s = W.step_valuation_reit("Realty Income", ffo, {"date": date(2026, 10, 16), "close": 57.0}, JPM_PERIODS)
    assert s["numbers"][0]["value"] == "13.3" and s["numbers"][0]["label"] == "Price to FFO" and "P/E" not in json.dumps(s)
    assert s["numbers"][0]["as_of"] == "Close Oct 16, 2026, FFO over the last four quarters, through Q2 2026"


def test_dividend_yield_cell():
    rows = [(date(2025, 10, 31) + timedelta(days=30 * i), 0.27) for i in range(12)]
    c = W_D.dividend_cell(rows, {"date": date(2026, 10, 16), "close": 57.0})
    assert c["value"] == "5.7%" and c["as_of"] == "12 dividends in the year to the Oct 16, 2026 close"
    assert W_D.dividend_cell([], {"date": date(2026, 10, 16), "close": 57.0}) is None


# ── Compare ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _side(reit=False, noun="sales", **rows):
    return {"reit": reit, "noun": noun, "rows": rows}


def _c(v, end=None):
    return {"value": v, "as_of": "y", **({"end": end} if end else {})}


def test_compare_sets_both_stocks_on_one_measure():
    tsla = _side(keeps_now={"gross": _c("19¢"), "operating": _c("5¢"), "net": _c("4¢")}, keeps_then={"gross": _c("22¢"), "operating": _c("9¢")})
    gm = _side(keeps_now={"operating": _c("1¢"), "net": _c("2¢")}, keeps_then={"operating": _c("7¢")})
    t = W.compare_table(tsla, gm)
    now = next(r for r in t if r["key"] == "keeps_now")
    assert now["label"] == "Keeps per $1 now (operating margin)" and now["a"]["value"] == "5¢" and now["b"]["value"] == "1¢"
    assert next(r for r in t if r["key"] == "keeps_then")["a"]["value"] == "9¢"
    jpm = _side(noun="revenue", keeps_now={"net": _c("33¢")}, growth={"ttm": _c("+13.5%")})
    aapl = _side(keeps_now={"gross": _c("49¢"), "operating": _c("32¢"), "net": _c("27¢")}, growth={"ttm": _c("+14.2%"), "quarter": _c("+16.4%")})
    t = W.compare_table(jpm, aapl)
    assert next(r for r in t if r["key"] == "keeps_now")["label"] == "Keeps per $1 now (profit margin)"
    assert next(r for r in t if r["key"] == "growth")["label"] == "Revenue growth"
    no_shared = W.compare_table(_side(keeps_now={"gross": _c("1¢")}), _side(keeps_now={"net": _c("2¢")}))
    assert not [r for r in no_shared if r["key"].startswith("keeps")]           # no measure both have: hidden
    spg = _side(True, growth={"quarter": _c("+8.2%")}, valuation={"p_ffo": _c("14.0")})
    o = _side(True, growth={"ttm": _c("+9.0%"), "quarter": _c("+9.7%")})
    g = next(r for r in W.compare_table(o, spg) if r["key"] == "growth")
    assert g["a"]["value"] == "+9.7%" and g["b"]["value"] == "+8.2%"             # one measure: both the latest quarter
    mixed = W.compare_table(_side(True, valuation={"p_ffo": _c("14.0")}), _side(valuation={"pe": _c("39.4")}))
    assert "valuation" not in [r["key"] for r in mixed]                          # P/E against price to FFO: hidden
    one = W.compare_table(_side(True), _side(valuation={"pe": _c("39.4")}))
    assert next(r for r in one if r["key"] == "valuation") == {"key": "valuation", "label": "P/E", "a": None, "b": _c("39.4")}


def test_compare_hides_rows_whose_periods_end_far_apart():
    o = _side(True, growth={"quarter": _c("+9.7%", "2026-06-30")})
    spg = _side(True, growth={"quarter": _c("+8.2%", "2025-09-30")})
    assert "growth" not in [r["key"] for r in W.compare_table(o, spg)]
    near = _side(True, growth={"quarter": _c("+8.2%", "2026-03-31")})
    assert "growth" in [r["key"] for r in W.compare_table(o, near)]             # 91 days apart: shown
    assert W.COMPARE_PERIOD_DAYS == 120


def test_compare_rows_hide_rows_both_lack_and_reit_pairs_get_reit_rows():
    cell = _c("x")
    mu, aapl = _side(sells={"share": cell}, keeps_now={"gross": cell}, valuation={"pe": cell}, dividend_yield={"close": cell}), _side(sells={"share": cell}, valuation={"pe": cell}, dividend_yield={"close": cell})
    assert [r["key"] for r in W.compare_table(mu, aapl)] == ["sells", "keeps_now", "valuation"]       # no dividend row for a non-trust pair
    o, spg = _side(True, growth={"quarter": cell}, dividend_yield={"close": cell}, stock_1y={"close": cell}), _side(True, dividend_yield={"close": cell}, valuation={"p_ffo": cell})
    assert [r["key"] for r in W.compare_table(o, spg)] == ["growth", "stock_1y", "valuation", "dividend_yield"]
    assert next(r for r in W.compare_table(o, spg) if r["key"] == "valuation")["label"] == "Price to FFO"


def test_compare_growth_falls_back_to_the_latest_quarter_with_its_name():
    rows = [{"metric": "revenue", "period_end": date(2026, 6, 30), "value": 1.5e9, "year_ago_value": 1.4e9, "growth_pct": 9.7, "phrase": "p", "held_reason": None, "readers": "X"}]
    s = W.step_growth("Realty Income", rows, "Real Estate", True, JPM_PERIODS, reit=True)
    assert s["cell"] == {"quarter": {"value": "+9.7%", "as_of": "Q2 2026, ended Jun 30, 2026, against a year earlier", "end": "2026-06-30"}}


def test_margins_by_measure_reads_every_measure_filed():
    rev = [(s, e, 100.0) for s, e in QUARTERS]
    facts = _facts({REV: rev, "GrossProfit": [(s, e, 40.0) for s, e in QUARTERS], "OperatingIncomeLoss": [(s, e, 10.0) for s, e in QUARTERS],
                    "NetIncomeLoss": [(s, e, 8.0) for s, e in QUARTERS]})
    out = M.margins(facts, "Information Technology", date(2026, 10, 19))
    assert out["measure"] == "gross" and {k: v["now"] for k, v in out["by_measure"].items()} == {"gross": 40.0, "operating": 10.0, "net": 8.0}
    banks = M.margins(facts, "Financials", date(2026, 10, 19))
    assert set(banks["by_measure"]) == {"net"}


# ── banks and insurers say revenue ─────────────────────────────────────────────────────────────────────────────────────────

def test_banks_and_insurers_say_revenue_everywhere():
    assert W.noun_for("Diversified Banks") == "revenue" and W.noun_for("Property & Casualty Insurance") == "revenue" and W.noun_for("Reinsurance") == "revenue"
    assert W.noun_for("Semiconductors") == "sales" and W.noun_for(None) == "sales"
    seg = {"ok": True, "filed": date(2026, 2, 13), "end": date(2025, 12, 31), "total": 182.4e9, "url": "u",
           "segments": [{"label": "Commercial & Investment Bank", "value": 78e9, "share": 43.0}, {"label": "Consumer & Community Banking", "value": 76e9, "share": 41.7}]}
    rows = [{"metric": "revenue", "period_end": date(2026, 6, 30), "value": 50e9, "year_ago_value": 40e9, "growth_pct": 27.7, "phrase": "p", "held_reason": None, "readers": "X"},
            {"metric": "eps", "period_end": date(2026, 6, 30), "value": 5.2, "year_ago_value": 3.5, "growth_pct": 46.9, "phrase": "p", "held_reason": None, "readers": "X"}]
    m = {"ok": True, "measure": "net", "label": "profit margin", "plain": "as profit after every cost", "now": 32.6, "then": 32.6,
         "now_start": date(2025, 7, 1), "now_end": date(2026, 6, 30), "then_end": date(2023, 6, 30), "revenue_tag": REV, "profit_tag": "NetIncomeLoss",
         "now_revenue": 1.0, "now_profit": 1.0, "then_revenue": 1.0, "then_profit": 1.0}
    steps = [W.step_business("JPMorgan Chase", {"short_description": "JPMorgan Chase is a bank."}, seg, None, JPM_PERIODS, "revenue"),
             W.step_growth("JPMorgan Chase", rows, "Financials", True, JPM_PERIODS, noun="revenue"),
             W.step_margins("JPMorgan Chase", m, [], JPM_PERIODS, "revenue")]
    text = json.dumps(steps)
    assert not re.search(r"\b[Ss]ales\b", text), re.findall(r".{40}\b[Ss]ales\b.{20}", text)
    assert steps[2]["question"] == "How much of each revenue dollar does it keep?"
    assert WS.output_problems("JPMorgan Chase's sales come from lending.", WS.STORY_WORDS, "business", "revenue")


# ── segment names as the 10-K writes them ─────────────────────────────────────────────────────────────────────────────────

def test_segment_names_follow_the_10k_text():
    text = S.document_text("<p>The Commercial &amp; Investment Bank (CIB) ... Commercial &amp; Investment Bank revenue</p><p>Services net sales ... Services</p>")
    assert S.text_name("Commercial And Investment Bank", text) == "Commercial & Investment Bank"
    assert S.text_name("Service", text) == "Services"
    assert S.text_name("Services And Other", "") == "Services and Other"
    assert S.text_name("Media And Entertainment [member]", "") == "Media and Entertainment"
    assert S.text_name("iPhone", "iPhone sales and iPhone models") == "iPhone"
    assert S.SEGMENTS_VERSION >= 2


def test_another_names_the_sub_industry_for_every_index_industry():
    assert W.another("Semiconductors") == "another semiconductor company"
    assert W.another("Diversified Banks") == "another diversified bank"
    assert W.another("Retail REITs") == "another retail REIT"
    assert W.another("Automobile Manufacturers") == "another automobile manufacturer"
    assert W.another("Systems Software") == "another systems software company"
    assert W.another("Technology Hardware, Storage & Peripherals") == "another technology hardware, storage and peripherals company"
    assert W.another("Electric Utilities") == "another electric utility" and W.another("Multi-Utilities") == "another multi-utility"
    assert W.another(None, "Information Technology") == "another information technology company"
    for ind in INDUSTRIES:
        label = W.another(ind)
        assert label.startswith("another ") and "&" not in label and not re.search(r"\b(?:Banks|REITs|Utilities|Manufacturers|Airlines)\b", label), label


INDUSTRIES = ("Advertising|Aerospace & Defense|Agricultural & Farm Machinery|Air Freight & Logistics|Apparel Retail|Application Software|"
              "Asset Management & Custody Banks|Automobile Manufacturers|Biotechnology|Consumer Finance|Data Center REITs|Distillers & Vintners|"
              "Distributors|Diversified Banks|Electric Utilities|Food Distributors|Health Care REITs|IT Consulting & Other Services|"
              "Independent Power Producers & Energy Traders|Insurance Brokers|Multi-Sector Holdings|Multi-Utilities|Passenger Airlines|Pharmaceuticals|"
              "Regional Banks|Restaurants|Semiconductors|Trading Companies & Distributors|Water Utilities").split("|")


# ── the line comparing two stocks on a known concept ──────────────────────────────────────────────────────────────────────

def test_every_shown_step_with_a_figure_serves_its_fact():
    rows = [{"metric": "revenue", "period_end": date(2026, 9, 3), "value": 54.2e9, "year_ago_value": 11.3e9, "growth_pct": 379.3, "phrase": "p", "held_reason": None, "readers": "X"}]
    f = W.step_growth("Micron", rows, "Information Technology", True, MU_PERIODS)["fact"]
    assert f == {"concept": "growth", "measure": "sales_yoy", "lead": "Micron's sales grew 379.3% from a year earlier", "short": "Micron's grew 379.3%",
                 "tail": "in fiscal Q4 2026"}
    m = {"ok": True, "measure": "gross", "label": "gross margin", "plain": "after paying for what it sold", "now": 80.7, "then": -9.1,
         "now_start": date(2025, 9, 1), "now_end": date(2026, 9, 3), "then_end": date(2023, 8, 31), "revenue_tag": REV, "profit_tag": "GrossProfit",
         "now_revenue": 1.0, "now_profit": 1.0, "then_revenue": 1.0, "then_profit": 1.0}
    assert W.step_margins("Micron", m, [], MU_PERIODS)["fact"]["measure"] == "gross"
    assert W.step_risks("X", {"ok": True, "filed": date(2026, 2, 1), "url": "u"}, None)["fact"] is None      # risks carry no figure: the full idea shows


# ── story sentences: Sam's rule (2026-10-19) ───────────────────────────────────────────────────────────────────────────────

def test_no_model_sentence_says_sensitive_exposed_or_what_may_happen_next_outside_the_risks():
    assert WS.STORY_VERSION >= 5
    for bad in ("Sales and earnings surged, making the company highly sensitive to any reversal in that momentum.",
                "Its chips are exposed to swings in memory prices.", "Keeping the bulk of each sales dollar is a sign of pricing power, yet this can reverse.",
                "The company warns profits may fall.", "Demand could slow next year."):
        assert WS.output_problems(bad, WS.STORY_WORDS, "margins"), bad
    risk = "Rivals including large corporations may use aggressive pricing to take market share."
    assert WS.output_problems(risk, WS.RISK_WORDS, "risk:2") == []                  # step 7 names the company's own risks
    assert WS.output_problems("Its sales are exposed to a few customers.", WS.RISK_WORDS, "risk:3")
    assert WS.output_problems("Memory chips go into phones and computers, so prices for them shape Micron's results.", WS.STORY_WORDS, "business") == []
    assert "sensitive" in WS.VOICE and "sensitive or exposed" in WS.verification_prompt({"name": "X"}, [("business", "A.")])


def test_a_step_story_never_states_its_checks_answer():
    assert WS.output_problems("Earnings grew faster than sales.", WS.STORY_WORDS, "growth")
    assert WS.output_problems("The company depends on a single product line.", WS.STORY_WORDS, "business")
    assert WS.output_problems("That rise reflects pricing power in a cyclical market.", WS.STORY_WORDS, "margins")
    assert WS.output_problems("Earnings grew faster than sales.", WS.STORY_WORDS, "does") == []


def test_step1_story_never_sizes_its_lines_and_figures_in_words_fail():
    assert WS.output_problems("Most of its revenue comes from banking, with consumer banking making up nearly all of the remainder.", WS.STORY_WORDS, "business")
    assert WS.output_problems("DRAM is a type of memory chip used in computers, phones and data centers.", WS.STORY_WORDS, "business") == []
    assert WS.output_problems("Sales have roughly doubled in a year.", WS.STORY_WORDS, "growth")


def test_summary_risk_line_keeps_names_capitalised():
    assert W.lead_lower("Micron competes against large rivals.", "Micron Technology") == "Micron competes against large rivals."
    assert W.lead_lower("JPMorgan Chase operates under supervision.", "JPMorgan Chase") == "JPMorgan Chase operates under supervision."
    assert W.lead_lower("Apple's markets are competitive.", "Apple") == "Apple's markets are competitive."
    assert W.lead_lower("Other buyers compete for properties.", "Realty Income") == "other buyers compete for properties."


def test_story_outlook_words_fail_outside_the_risks():
    assert WS.output_problems("Watching whether sales keep climbing tells you how the model is holding up.", WS.STORY_WORDS, "growth")
    assert WS.output_problems("Sales rose at a solid pace, reflecting its effort to add properties.", WS.STORY_WORDS, "growth")
    assert WS.output_problems("Each sale now brings in more profit.", WS.STORY_WORDS, "growth")
