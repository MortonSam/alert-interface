"""The second reader: the model's quote is verified by code, and a figure stores only when both readers agree to the cent."""
from datetime import date

from app.services import release_reader as R
from app.services.notify import digest_message

EXHIBIT = ("Fourth quarter revenue increased 6% to $63.7 billion and GAAP diluted earnings per share (EPS) increased 70% to $1.70. "
           "Non-GAAP diluted EPS increased 40% to $2.91. Fiscal year 2026 revenues were $254.2 billion. GAAP diluted EPS was $7.23. "
           "Reported Income (loss) per common share from continuing operations - diluted $ 0.37 $ 0.88")


def test_the_quote_must_be_verbatim_carry_the_number_and_no_disqualifier():
    assert R.verify_quote(EXHIBIT, "Fourth quarter revenue increased 6% to $63.7 billion and GAAP diluted earnings per share (EPS) increased 70% to $1.70.", 1.70) == []
    assert R.verify_quote(EXHIBIT, "GAAP diluted EPS rose to $1.70 in the quarter.", 1.70) == ["quote is not verbatim in the exhibit"]
    assert R.verify_quote(EXHIBIT, "Non-GAAP diluted EPS increased 40% to $2.91.", 2.91) == ["disqualifying word(s): non-gaap"]
    assert R.verify_quote(EXHIBIT, "Fiscal year 2026 revenues were $254.2 billion. GAAP diluted EPS was $7.23.", 7.23) == ["disqualifying word(s): fiscal year"]
    assert R.verify_quote(EXHIBIT, "Reported Income (loss) per common share from continuing operations - diluted $ 0.37 $ 0.88", 0.37, None, 1) == ["continuing operations without a total"]
    assert R.verify_quote(EXHIBIT, "GAAP diluted EPS was $7.23.", 1.70) == ["quote does not contain +1.70"]
    assert R.verify_quote(EXHIBIT, None, 1.70) == ["no quote"]
    assert R.verify_quote("GAAP loss per share of $(0.03)", "GAAP loss per share of $(0.03)", -0.03) == []
    # formatting is not wording: the model's spacing of a table row still matches the exhibit (CLX, VRSK, WDC on the 2026-10-07 dry run)
    assert R.verify_quote("Diluted net earnings per share $1.34 $2.68 (50)%", "Diluted net earnings per share $ 1.34 $ 2.68 (50) %", 1.34, None, 1) == []
    assert R.verify_quote("Diluted EPS attributable to Verisk $1.75 $1.81 (3.3) 3.48", "Diluted EPS attributable to Verisk $ 1.75 $ 1.81 (3.3 ) 3.48", 1.75, None, 1) == []
    assert R.verify_quote("Diluted EPS $1.75", "Diluted EPS $1.57", 1.57) == ["quote is not verbatim in the exhibit"]        # a different number is a different quote


def test_store_only_on_agreement_to_the_cent_and_the_notes_carry_both_readings():
    pattern = {"eps": 1.70, "how": "GAAP EPS change sentence"}
    good = {"eps": 1.70, "quote": "Fourth quarter revenue increased 6% to $63.7 billion and GAAP diluted earnings per share (EPS) increased 70% to $1.70."}
    assert R.decide(pattern, good, EXHIBIT) == (1.70, "both readers +1.70")
    assert R.agree(1.70, 1.704) and not R.agree(1.70, 1.71) and not R.agree(None, 1.70)
    figure, note = R.decide(pattern, {"eps": 7.23, "quote": "GAAP diluted EPS was $7.23."}, EXHIBIT)
    assert figure is None and note.startswith("pattern +1.70 (GAAP EPS change sentence); model +7.23") and "readers disagree" in note
    figure, note = R.decide(pattern, {"eps": 2.91, "quote": "Non-GAAP diluted EPS increased 40% to $2.91."}, EXHIBIT)
    assert figure is None and "model quote rejected: disqualifying word(s): non-gaap" in note
    figure, note = R.decide(None, good, EXHIBIT)
    assert figure is None and note.startswith("pattern read nothing; model +1.70")
    figure, note = R.decide(pattern, {"eps": None, "quote": None}, EXHIBIT)
    assert figure is None and "model read nothing" in note
    figure, note = R.decide(pattern, None, EXHIBIT)
    assert figure is None and "no model reading" in note
    body = digest_message("2026-10-08", 30, 30, [], None, 90.0, None, release_disagreements=["CRL 2026-08-05: pattern +3.02 (GAAP EPS sentence); model -0.03; readers disagree"])[1]
    assert "release EPS readers disagree (1), left unread: CRL 2026-08-05: pattern +3.02" in body


def test_the_prompt_names_every_rule_and_the_model_json_is_parsed():
    prompt, cut = R.build_prompt("  some   text ", date(2026, 8, 11))
    assert not cut and "some text" in prompt and "2026-08-11" in prompt
    for word in ("never the fiscal year", "never non-GAAP", "never FFO", "never continuing operations alone", "verbatim", "a loss is negative"):
        assert word in prompt, word
    assert R.build_prompt("x" * (R.MAX_CHARS + 5), None)[1] is True
    assert R.parse_model_json('Here: {"eps": -0.35, "period_end": "2026-07-31", "quote": "GAAP net loss of $(0.35) per diluted share"}') == {"eps": -0.35, "period_end": date(2026, 7, 31), "quote": "GAAP net loss of $(0.35) per diluted share", "columns": None, "column": None}
    assert R.parse_model_json('{"eps": null, "period_end": null, "quote": null}') == {"eps": None, "period_end": None, "quote": None, "columns": None, "column": None}
    assert R.parse_model_json("no json here") is None


CLX = ("comparable GAAP measure: Adjusted Diluted Earnings Per Share (EPS) (Dollars in millions except per share data) Diluted earnings per share "
       "Three months ended 6/30/2026 6/30/2025 % Change As reported (GAAP) $ 1.34 $ 2.68 (50) % Acquisition and integration costs (2) 0.05 "
       "Adjusted (non-GAAP) $ 1.39 $ 2.70 (49) % ... Net earnings per share attributable to Clorox Basic net earnings per share $ 1.34 $ 2.70 "
       "Diluted net earnings per share $ 1.34 $ 2.68 $ 4.81 $ 6.52 Weighted average shares")


def test_a_quote_verbatim_in_pieces_stands_when_the_exhibits_own_row_label_is_clean():
    """CLX, 2026-10-07 production run: the model copied the row's numbers from the reconciliation table ("As reported (GAAP) $ 1.34 $ 2.68
    (50) %") under the income statement's label. Each piece is verbatim and the exhibit's own label on that row carries no disqualifier."""
    assert R.verify_quote(CLX, "Diluted net earnings per share $ 1.34 $ 2.68 (50) %", 1.34, "Three months ended 6/30/2026 6/30/2025", 1) == []
    # the same numbers under a non-GAAP row in the exhibit cannot be laundered with a GAAP label
    assert R.verify_quote(CLX, "Diluted net earnings per share $ 1.39 $ 2.70 (49) %", 1.39, None, 1) == ["the exhibit's row is labelled with disqualifying word(s): adjusted, non-gaap"]
    assert R.verify_quote(CLX, "Diluted net earnings per share $ 1.44 $ 2.68 (50) %", 1.44, None, 1) == ["quote is not verbatim in the exhibit"]


def test_zero_width_characters_and_unicode_dashes_are_formatting():
    """DLR, 2026-10-07: its EX-99 carries a zero-width space in every cell, which Python's whitespace class does not cover."""
    exhibit = "Net income available to common stockholders per diluted share \u200b \u200b $0.76 \u200b \u200b $0.47"
    assert R.verify_quote(exhibit, "Net income available to common stockholders per diluted share $0.76 $0.47", 0.76, None, 1) == []
    assert R.verify_quote("Diluted loss per share \u2013 GAAP $ \u2212 0.35", "Diluted loss per share - GAAP $ -0.35", -0.35) == []


def test_a_row_of_several_figures_needs_the_column_read_and_it_must_follow_the_heading():
    ford = "Second Quarter First Half 2025 2026 Change 2025 2026 Change EPS (Diluted) $ (0.01) $ (0.33) $ (0.32) $ 0.11 $ 0.30 $ 0.19"
    assert R.verify_quote(ford, "EPS (Diluted) $ (0.01) $ (0.33) $ (0.32) $ 0.11 $ 0.30 $ 0.19", -0.33, "Second Quarter First Half 2025 2026 Change", 2) == []
    assert R.verify_quote(ford, "EPS (Diluted) $ (0.01) $ (0.33) $ (0.32) $ 0.11 $ 0.30 $ 0.19", -0.01, "Second Quarter First Half 2025 2026 Change", 1) == [
        "the heading lists the prior year first but column 1 was read"]
    assert R.verify_quote(ford, "EPS (Diluted) $ (0.01) $ (0.33) $ (0.32) $ 0.11 $ 0.30 $ 0.19", -0.33, None, None) == ["a row of several figures without the column read"]
    assert R.verify_quote(ford, "EPS (Diluted) $ (0.01) $ (0.33) $ (0.32) $ 0.11 $ 0.30 $ 0.19", -0.33, None, 1) == ["column 1 does not hold -0.33"]
    assert R.verify_quote(ford, "EPS (Diluted) $ (0.01) $ (0.33)", -0.33, "Three Months Ended 2026 2025", 2) == [
        "the heading is not verbatim in the exhibit", "the heading lists the current period first but column 2 was read"]
    # a sentence with one figure needs no column
    assert R.verify_quote(EXHIBIT, "GAAP diluted earnings per share (EPS) increased 70% to $1.70.", 1.70) == []
    parsed = R.parse_model_json('{"eps": -0.33, "period_end": "2026-06-30", "quote": "EPS (Diluted) $ (0.01) $ (0.33)", "columns": "2025 2026", "column": "2"}')
    assert (parsed["columns"], parsed["column"]) == ("2025 2026", 2)
    assert R.parse_model_json('{"eps": 1.7, "quote": "x", "columns": null, "column": null}')["column"] is None
    assert "read the heading, never assume the first number" in R.PROMPT and '"column":' in R.PROMPT


def test_a_financial_supplement_reads_after_the_press_release():
    """DLR files its financial supplement as EX-99.1 and the release as EX-99.2; the supplement (five quarters across the page, zero-width
    spaces in every cell, 125k characters) was read first and cut at MAX_CHARS. The release reads first."""
    from app.scripts.seed_release_eps import exhibit_candidates
    supplement = ("dlr-20260723xex99d1.htm", "Digital Realty Reports Second Quarter 2026 Results Financial Supplement Unaudited " + "x " * 400)
    release = ("dlr-20260723xex99d2.htm", "Digital Realty Reports Second Quarter 2026 Results Net income per diluted share $0.76 " + "y " * 400)
    assert [n for n, _ in exhibit_candidates([supplement, release])] == [release[0], supplement[0]]
    assert [n for n, _ in exhibit_candidates([release, supplement])] == [release[0], supplement[0]]
    slides = ("q226presentationfinal8k.htm", "Second Quarter 2026 Earnings Call presentation " + "z " * 400)
    assert [n for n, _ in exhibit_candidates([slides, release])] == [release[0], slides[0]]
