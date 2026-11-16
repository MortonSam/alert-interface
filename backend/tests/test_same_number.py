"""Same number, same answer (Sam's overnight comparison, 2026-11-12): a figure a visitor can meet in two places reads the same in
both, and the nightly validate lists every stock where it does not."""
from datetime import date

from app.scripts.validate_data import CHECKS, SAME_NUMBER_ANY_BASIS, SAME_NUMBER_TOLERANCE, check_same_number_same_answer, same_number_pairs, shown_number

Q2, Q3 = date(2026, 6, 30), date(2026, 9, 30)
CLOSE = date(2026, 11, 10)


def test_a_displayed_figure_is_read_back_as_its_number():
    assert shown_number("+12.1%") == 12.1 and shown_number("−4.6%") == -4.6 and shown_number("-4.6%") == -4.6
    assert shown_number("$1,234.50") == 1234.5 and shown_number("±6.9%") == 6.9 and shown_number("$22") == 22
    assert shown_number("no figure") is None and shown_number(None) is None


def test_two_readings_on_one_basis_disagree_past_the_tolerance_only():
    pairs = same_number_pairs({
        "AMZN": {"revenue growth": [("walkthrough", 12.1, Q3), ("ticker page growth rows", 12.1, Q3)],        # the same
                 "P/E": [("walkthrough", 22.0, CLOSE), ("ticker page", 21.93, CLOSE)]},                         # whole dollars against two decimals
        "AAPL": {"trailing EPS": [("walkthrough", 8.31, CLOSE), ("ticker page", 8.32, CLOSE)]},                 # a cent apart on one close
        "MU": {"revenue growth": [("walkthrough", 46.0, Q3), ("ticker page growth rows", 45.4, Q3)]},
        "JPM": {"P/E": [("walkthrough", 14.0, date(2026, 11, 9)), ("ticker page", 15.2, CLOSE)]},               # another close: not the same figure
        "XOM": {"P/E": [("walkthrough", None, CLOSE), ("ticker page", 15.2, CLOSE)]},                           # shown in one place only
    })
    assert pairs == {"trailing EPS": ["AAPL: walkthrough 8.31, ticker page 8.32"],
                     "revenue growth": ["MU: walkthrough 46.0, ticker page growth rows 45.4"]}


def test_a_date_a_word_or_a_sample_that_differs_is_itself_the_disagreement():
    pairs = same_number_pairs({
        "AMZN": {"latest quarter": [("walkthrough", Q3, None), ("ticker page growth rows", Q2, None)]},
        "JNJ": {"next report": [("walkthrough", date(2027, 1, 19), None), ("ticker header", date(2027, 1, 19), None), ("Ivy's Read", date(2027, 1, 26), None)]},
        "ADBE": {"options word": [("ticker page (+8.7)", "neither", None), ("Build a Trade and Discover", "rich", None)]},
        "NVDA": {"options word": [("ticker page (+19.7)", "rich", None), ("Build a Trade and Discover", "rich", None)],
                 "typical move": [("walkthrough", 6.9, "21 reports"), ("report history", 7.4, "22 reports")]},
        "KO": {"typical move": [("walkthrough", 2.1, "20 reports"), ("report history", 2.1, "21 reports")]},     # a report more, the same answer
        "JPM": {"revenue growth, note tile": [("research note", 109.0, "trailing year"), ("ticker page growth rows", 8.1, "latest quarter")]},
        "LLY": {"revenue growth, note tile": [("research note", 38.0, "trailing year"), ("ticker page growth rows", 45.0, "latest quarter")]},
    })
    assert pairs == {
        "latest quarter": ["AMZN: walkthrough 2026-09-30, ticker page growth rows 2026-06-30"],
        "next report": ["JNJ: walkthrough 2027-01-19, Ivy's Read 2027-01-26"],            # one line a stock, the first pair that differs
        "options word": ["ADBE: ticker page (+8.7) neither, Build a Trade and Discover rich"],
        "typical move": ["NVDA: walkthrough 6.9, report history 7.4 (21 reports against 22 reports)"],
        "revenue growth, note tile": ["JPM: research note 109.0, ticker page growth rows 8.1 (trailing year against latest quarter)"],
    }


def test_the_check_runs_nightly_and_every_figure_it_names_has_a_rule():
    assert check_same_number_same_answer in CHECKS
    # a figure compared across bases is a date, a word, or a number with a tolerance of its own
    assert {"typical move", "revenue growth, note tile"} <= SAME_NUMBER_ANY_BASIS & set(SAME_NUMBER_TOLERANCE)
    assert all(t > 0 for t in SAME_NUMBER_TOLERANCE.values())


def test_the_options_word_is_one_rule():
    """The ticker page, Ivy's Read, Build a Trade and Discover word the options by one pair of cutoffs (item 7, 2026-11-16), so the
    check's two readings of the options word can never differ."""
    from app.thresholds import SPREAD_CHEAP_PP, SPREAD_RICH_PP, spread_label, vol_regime_label
    word = lambda label: "neither" if label is None or label.label == "in line" else label.label.split()[-1]
    probes = [SPREAD_CHEAP_PP - 0.1, SPREAD_CHEAP_PP, SPREAD_CHEAP_PP + 0.1, -12, -7, 0, 9, 12, SPREAD_RICH_PP - 0.1, SPREAD_RICH_PP, SPREAD_RICH_PP + 0.1]
    assert [x for x in probes if word(spread_label(x)) != word(vol_regime_label(x))] == []
    assert {word(spread_label(x)) for x in (-50, 0, 50)} == {word(vol_regime_label(x)) for x in (-50, 0, 50)} == {"cheap", "neither", "rich"}
