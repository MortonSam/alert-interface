"""Discover blurbs: one template per fact, from the values the chips use."""
import re
from pathlib import Path

from app.services.discover_blurbs import earnings_blurb, reaction_blurb, volatility_blurb
from app.thresholds import rv_rank_label

DISCOVER = (Path(__file__).resolve().parents[1] / "app" / "routers" / "discover.py").read_text()


def test_earnings_card_has_one_template_per_fact():
    priced_in = {"total": 20, "beat_count": 18, "bbd_count": 11, "avg_1d_on_beat": 1.2, "avg_abs_1d": 4.1}
    assert earnings_blurb(priced_in) == "Beat 18 of 20; the stock fell after 61% of those beats"
    assert earnings_blurb(dict(priced_in, total=16, beat_count=13, bbd_count=6)) == "Beat 13 of 16; the stock fell after 46% of those beats"
    # 3 of 18 beats fell (17%): below the priced-in cutoff, so the beat rate is the fact
    assert earnings_blurb({"total": 20, "beat_count": 18, "bbd_count": 3, "avg_1d_on_beat": 1.9, "avg_abs_1d": 4.0}) == "Beat 18 of 20, averaging +1.9% on the 1-day reaction to a beat"
    high_rate = {"total": 8, "beat_count": 7, "bbd_count": 1, "avg_1d_on_beat": 2.7, "avg_abs_1d": 5.0}
    assert earnings_blurb(high_rate) == "Beat 7 of 8, averaging +2.7% on the 1-day reaction to a beat"
    plain = {"total": 12, "beat_count": 5, "bbd_count": 1, "avg_1d_on_beat": None, "avg_abs_1d": 6.3}
    assert earnings_blurb(plain) == "Earnings move averages ±6.3% over 12 quarters"
    assert earnings_blurb({"total": 3, "beat_count": 3, "bbd_count": 0}) is None


def test_volatility_card_uses_the_chip_words():
    tier = rv_rank_label(92).label
    assert volatility_blurb(-33.0, "iv_cheap", 92) == f"IV cheap at -33pp vs realized · RV rank 92, {tier}"
    assert volatility_blurb(8.0, "iv_rich", 87) == f"IV rich at +8pp vs realized · RV rank 87, {rv_rank_label(87).label}"
    assert volatility_blurb(3.0, None, 87) == f"IV in line with realized at +3pp vs realized · RV rank 87, {rv_rank_label(87).label}"
    assert volatility_blurb(None, None, 87) == f"RV rank 87, {rv_rank_label(87).label}"
    assert volatility_blurb(5.0, "iv_rich", None) is None


def test_reaction_card_has_one_template():
    cond = {"total": 12, "avg_abs_1d": 4.0, "avg_1d_on_beat": 2.7, "avg_1d_on_miss": -5.1}
    assert reaction_blurb(-6.3, "beat", cond) == "Moved -6.3% on the 1-day reaction; its typical beat moves +2.7%"
    assert reaction_blurb(1.0, "meet", cond) == "Moved +1.0% on the 1-day reaction; its typical earnings move is ±4.0%"
    assert reaction_blurb(None, "beat", cond) is None


def test_every_card_renders_through_the_blurb_module():
    assert "earnings_blurb(cond)" in DISCOVER
    assert 'volatility_blurb(vol.get("iv_rv_spread_pp"), vol.get("vol_regime"), vol.get("rv_rank"))' in DISCOVER
    assert "_sym_variant" not in DISCOVER
    for old in ("of beats dropped", "but stock fell", "pp spread", "Options {label", "Implied-realized gap", "templates = ["):
        assert old not in DISCOVER, old
    # the card builders still call the wrappers
    assert "reaction_blurb(pct_1d, outcome, cond)" in DISCOVER
    assert "insight=_reporting_soon_insight(cond, r.symbol)" in DISCOVER
    assert "insight=_unusually_active_insight(vol_data.get(row.symbol), row.symbol)" in DISCOVER
