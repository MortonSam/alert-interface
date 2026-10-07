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
    assert R.verify_quote(EXHIBIT, "Reported Income (loss) per common share from continuing operations - diluted $ 0.37 $ 0.88", 0.37) == ["continuing operations without a total"]
    assert R.verify_quote(EXHIBIT, "GAAP diluted EPS was $7.23.", 1.70) == ["quote does not contain +1.70"]
    assert R.verify_quote(EXHIBIT, None, 1.70) == ["no quote"]
    assert R.verify_quote("GAAP loss per share of $(0.03)", "GAAP loss per share of $(0.03)", -0.03) == []
    # formatting is not wording: the model's spacing of a table row still matches the exhibit (CLX, VRSK, WDC on the 2026-10-07 dry run)
    assert R.verify_quote("Diluted net earnings per share $1.34 $2.68 (50)%", "Diluted net earnings per share $ 1.34 $ 2.68 (50) %", 1.34) == []
    assert R.verify_quote("Diluted EPS attributable to Verisk $1.75 $1.81 (3.3) 3.48", "Diluted EPS attributable to Verisk $ 1.75 $ 1.81 (3.3 ) 3.48", 1.75) == []
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
    assert R.parse_model_json('Here: {"eps": -0.35, "period_end": "2026-07-31", "quote": "GAAP net loss of $(0.35) per diluted share"}') == {"eps": -0.35, "period_end": date(2026, 7, 31), "quote": "GAAP net loss of $(0.35) per diluted share"}
    assert R.parse_model_json('{"eps": null, "period_end": null, "quote": null}') == {"eps": None, "period_end": None, "quote": None}
    assert R.parse_model_json("no json here") is None
