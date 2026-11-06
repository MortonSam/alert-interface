"""Build a Trade drafts from rules (services/draft_rules, Sam 2026-11-03): no model call, the prompt's guides applied in code."""
from app.services import draft_copy as DC
from app.services.draft_rules import draft, long_leg, short_leg, structure_for, target_for

ROWS = [{"strike": k, "mid": m} for k, m in [(90, 12.0), (95, 8.0), (100, 5.0), (105, 2.8), (110, 1.4), (115, 0.7), (120, 0.3)]]


def test_structure_follows_the_vol_regime_and_risk():
    assert structure_for("conservative", "iv_rich") == "spread" and structure_for("aggressive", "iv_rich") == "long"
    assert structure_for("conservative", "iv_cheap") == "long"
    assert structure_for("conservative", "iv_fair") == "spread" and structure_for("moderate", None) == "long"


def test_strikes_by_risk_and_never_past_ten_percent_outright():
    assert long_leg("bullish", "conservative", ROWS, 101)["strike"] == 100       # at the money or just inside
    assert long_leg("bullish", "moderate", ROWS, 101)["strike"] == 105           # the first strike past the price
    assert long_leg("bullish", "aggressive", ROWS, 101)["strike"] == 110          # the third past, capped by the 10% rule
    assert long_leg("bearish", "conservative", ROWS, 101)["strike"] == 105
    assert long_leg("bearish", "moderate", ROWS, 101)["strike"] == 100
    assert long_leg("bearish", "aggressive", ROWS, 101)["strike"] == 95           # 90 is past 10%
    assert short_leg("bullish", ROWS, 100, 108)["strike"] == 110
    assert short_leg("bullish", ROWS, 100, 200)["strike"] == 120                  # none reaches: the farthest


def test_a_draft_targets_the_risk_levels_share_of_the_implied_move():
    assert target_for("bullish", "moderate", 100, 0.08) == 108.0
    assert target_for("bearish", "conservative", 100, 0.08) == 94.8
    d = draft("bullish", "conservative", "iv_rich", ROWS, 101, 0.08, 0.06)
    assert (d.structure, d.long_strike, d.short_strike, d.short_reaches) == ("spread", 100, 110, True) and d.target == 106.25
    assert d.flag is None                                                         # a 5.2% move, inside the 6% largest
    far = draft("bullish", "aggressive", "iv_cheap", ROWS, 101, 0.08, 0.06)
    assert far.structure == "long" and far.flag == "beyond_history"             # a 14% move past the 6% largest
    assert draft("bullish", "moderate", None, ROWS, 101, None, 0.06) is None      # no implied move, no own target: no draft
    assert draft("bullish", "moderate", None, ROWS, 101, None, 0.06, proposed_target=104).target == 104


def test_every_sentence_is_plain_and_gives_no_advice():
    import re
    lines = [DC.vol_sentence("X", r, 9.1, s) for r in ("iv_rich", "iv_cheap", "iv_fair", None) for s in ("spread", "long")]
    lines += [DC.history_sentence("X", 20, 3.1, 7.6), DC.target_sentence(106.25, "moderate", 8.0, "Nov 20, 2026"), DC.target_own(104),
              DC.spread_sentence("call", 110), DC.spread_sentence("call", 110, False), DC.analyst_sentence("X", "bullish", 21, 1.67),
              DC.flag_beyond_history(115, 14.0, 6.0, 20), DC.flag_beyond_implied(120, 18.8, 8.0)] + [DC.strike_sentence(r, "call") for r in DC.STRIKE_WHY]
    for line in lines:
        assert not re.search(r"\b(?:you should|buy now|sell now|recommend|consider buying|a good trade)\b", line, re.I), line
        assert "—" not in line and ":" not in line, line
