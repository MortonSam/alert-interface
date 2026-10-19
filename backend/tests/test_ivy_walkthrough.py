"""Ivy's walkthrough: the 10-K readers, the margin measure, every quick-check template with worked examples, the step builders'
honest absences (the VMRK rule, the flags), the rival and featured rules, and the story sentences' output check. All pure."""
from __future__ import annotations

from datetime import date

from app.services import margins as M
from app.services import risk_factors as R
from app.services import segments as S
from app.services import walkthrough as W
from app.services import walkthrough_checks as C
from app.services import walkthrough_compare as WC
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


# ── quick checks: worked examples for every template ──────────────────────────────────────────────────────────────────────

def test_segments_check():
    c = C.segments_check("Micron", [{"label": "DRAM", "value": 76, "share": 75.6}, {"label": "NAND", "value": 24, "share": 23.9}], "fiscal year to Sep 3, 2026")
    assert c["options"] == ["DRAM", "NAND"] and c["options"][c["answer"]] == "DRAM" and "75.6%" in c["why"]
    assert C.segments_check("X", [{"label": "A", "value": 1, "share": 100.0}], "p") is None


def test_growth_check():
    for pct, word in ((167.0, "Grew"), (-12.5, "Shrank"), (1.9, "About flat"), (-1.9, "About flat"), (2.0, "Grew")):
        c = C.growth_check("Micron", pct, "four quarters")
        assert c["options"][c["answer"]] == word


def test_margins_check():
    c = C.margins_check("Apple", 46.9, "after paying for what it sold")
    assert c["options"][c["answer"]] == "About $47" and len(set(c["options"])) == 3
    c = C.margins_check("JPM", 30.0, "as profit after every cost")
    assert c["options"][c["answer"]] == "About $30" and "About $70" in c["options"] and "About $3" in c["options"]


def test_cyclical_check():
    assert C.is_cyclical(80.7, -9.1) and not C.is_cyclical(48.7, 43.4) and not C.is_cyclical(50.0, None)
    c = C.cyclical_check("Micron", 80.7, -9.1)
    assert c["answer"] == 0 and "lost 9¢ on each sales dollar" in c["question"] and "keeps 81¢ of each one" in c["question"]


def test_market_check_and_the_owner_rule():
    assert C.move_owner(18.4, 1.7, 1.0) == "company"           # SPY moved, but under half the stock's move
    assert C.move_owner(-3.0, -2.0, 1.0) == "market"           # same way, at least the minimum, at least half
    assert C.move_owner(-3.0, 2.0, 1.0) == "company"           # the other way
    assert C.move_owner(1.2, 0.8, 1.0) == "company"            # SPY under MARKET_DAY_MIN_SPY_PCT
    assert C.move_owner(5.0, None, 1.0) == "company"           # no SPY figure is never guessed
    c = C.market_check("Micron", "Jul 30, 2026", 18.4, 1.7, 1.0)
    assert c["options"][c["answer"]] == "The company"
    c = C.market_check("JPM", "Apr 7, 2025", -3.0, -2.0, 1.0)
    assert c["options"][c["answer"]] == "The market"


def test_pe_check():
    for pe, med, word in ((11.8, 16.7, "Less than usual"), (39.4, 34.3, "More than usual"), (14.2, 14.4, "About the same as usual")):
        c = C.pe_check("X", pe, med)
        assert c["options"][c["answer"]] == word


def test_report_move_checks():
    assert C.report_move_check("X", 7.5, 6.0)["answer"] == 0       # 1.25x: bigger than usual
    assert C.report_move_check("X", 4.0, 6.0)["answer"] == 1       # 0.67x: smaller
    assert C.report_move_check("X", 6.0, 6.0)["answer"] == 2
    c = C.typical_move_check("Micron", 6.8)
    assert c["options"][c["answer"]] == "About $7" and c["options"] == ["About $2", "About $7", "About $28"]


def test_risk_check():
    c = C.risk_check("Micron", "Chip prices swing widely.")
    assert c["answer"] == 1 and "disclosure" in c["why"]


def test_every_check_is_free_of_colons_and_em_dashes():
    checks = [C.segments_check("A", [{"label": "B", "value": 2, "share": 60.0}, {"label": "C", "value": 1, "share": 40.0}], "p"), C.growth_check("A", 3, "p"),
              C.margins_check("A", 40, "after paying for what it sold"), C.cyclical_check("A", 40, 10), C.market_check("A", "d", 3, 2, 1),
              C.pe_check("A", 10, 12), C.report_move_check("A", 5, 4), C.typical_move_check("A", 5), C.risk_check("A", "B.")]
    for c in checks:
        text = " ".join([c["question"], c["why"], *c["options"]])
        assert ":" not in text and "—" not in text, text


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
    assert s["sentences"][0] == "Micron keeps 81¢ of each sales dollar after paying for what it sold, up from a loss of 9¢ three years earlier."
    assert s["idea"]["concept"] == "cyclical"
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
               "compare": {"rows": {"growth": {"value": "+1%"}, "pe": {"value": "11.8"}}}}
    out = gate(payload, growth_on=False, pe_on=False)
    assert out["steps"][1]["status"] == "absent" and W.GROWTH_IN_REVIEW in out["steps"][1]["absent"]
    assert out["steps"][4]["status"] == "absent" and W.PE_IN_REVIEW in out["steps"][4]["absent"]
    assert out["compare"]["rows"]["growth"] is None and out["compare"]["rows"]["pe"] is None
    assert not out["summary"]["known"][1]["shown"] and payload["steps"][1]["status"] == "ok"      # the stored payload is untouched
    assert gate(payload, True, True)["steps"][1]["status"] == "ok"


def test_pe_series_median_is_the_stored_median():
    quarters = [{"start": date(2020, 1, 1) + (date(2020, 4, 1) - date(2020, 1, 1)) * i, "end": date(2020, 3, 31) + (date(2020, 6, 30) - date(2020, 3, 31)) * i,
                 "eps": 1.0 + 0.1 * i, "filed": date(2020, 5, 1) + (date(2020, 8, 1) - date(2020, 5, 1)) * i, "derived": False} for i in range(20)]
    bars = [(date(2021, 6, 1) + (date(2021, 6, 2) - date(2021, 6, 1)) * k, 50.0 + k % 30) for k in range(1000)]
    from statistics import median
    series = V.pe_series_clean(bars, quarters, [])
    assert round(median(v for _, v in series), 1) == V.pe_history_clean(bars, quarters, 20.0, [])["median"]


def test_summary_marks_absent_steps_and_lists_concepts_once():
    steps = [W._step(1, status="ok", idea="segments", summary="A."), W._step(2, status="absent", idea="growth", absent="x"),
             W._step(3, status="ok", idea="margins", summary="C.", uncertain="U.")] + [W._step(n, status="absent", idea=None) for n in range(4, 8)]
    s = W.summary("Micron", steps)
    assert s["known"][1] == {"n": 2, "line": "Not shown for Micron yet (is the business getting bigger).", "shown": False}
    assert [c["concept"] for c in s["concepts"]] == ["segments", "margins"] and s["uncertain"] == ["U."] and s["closing"] == W.CLOSING_LINE


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
    WS.apply(payload, {"sentences": {"business": "Story.", "risk:4": "Rivals cut prices."}})
    assert payload["steps"][0]["story"] == "Story." and payload["steps"][1]["story"] is None
    assert payload["steps"][6]["status"] == "ok" and payload["steps"][6]["risks"] == [{"n": 4, "sentence": "Rivals cut prices."}]
    assert payload["steps"][6]["check"]["concept"] == "risk_factors"


def test_growth_falls_back_to_the_newest_agreed_quarter_and_never_prints_iso_dates():
    rows = [{"metric": "revenue", "period_end": date(2026, 3, 31), "value": 110, "year_ago_value": 100, "growth_pct": 10.0, "phrase": "up 10.0% from a year earlier",
             "held_reason": None, "readers": "XBRL and the earnings release / XBRL and the earnings release"},
            {"metric": "revenue", "period_end": date(2026, 6, 30), "value": None, "year_ago_value": None, "growth_pct": None, "phrase": None, "held_reason": None, "readers": None}]
    s = W.step_growth("Micron", rows, "Information Technology", True)
    assert s["status"] == "partial" and s["numbers"][0]["as_of"] == "Quarter to Mar 31, 2026"
    held = W.step_growth("Micron", [{**rows[0], "period_end": date(2026, 6, 30), "held_reason": "Spun off Qnity on 2025-11-01, inside the year compared"}], None, True)
    assert held["absent"] == "Ivy can't show this for Micron yet. Spun off Qnity on Nov 1, 2025, inside the year compared."


def test_nightly_cost_guards_compare_sentences_and_margins_change_only_with_filings():
    from app.scripts.build_walkthroughs import latest_periodic
    side = lambda **rows: {"compare": {"rows": {"sells": {"value": "DRAM"}, "growth": None, "keeps_now": None, "keeps_then": None, **rows}},
                           "steps": [{"key": "business", "status": "ok"}]}
    a, b = side(stock_1y={"value": "+1%"}, pe={"value": "11.8"}), side()
    assert WS.compare_fingerprint(a, b) == WS.compare_fingerprint(side(stock_1y={"value": "+9%"}, pe={"value": "12.4"}), b)   # prices move nightly
    assert WS.compare_fingerprint(a, b) != WS.compare_fingerprint(side(sells={"value": "NAND"}), b)
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
