"""VMRK (2026-10-15): a company that took in another after its profile was written describes the merger, never the old company;
a market value from a share count that disagrees with the dated market cap is left out."""
from datetime import date

from app.services import briefing as B

EQR_TEXT = ("Equity Residential is committed to creating communities where people thrive. Equity Residential owns or has investments in "
            "305 properties consisting of 78,568 apartment units. The Company is a member of the S&P 500.")


def test_merger_after_the_profile_replaces_the_description():
    s = B.profile_sentence(name="Vivmark Residential", symbol="VMRK", short_description=EQR_TEXT, profile_as_of=date(2026, 10, 6),
                           gics_sector="Real Estate", gics_sub_industry="REIT - Residential", index_member=True,
                           profile_filed=date(2026, 7, 30), merged_name="AvalonBay Communities, Inc.", merged_on=date(2026, 8, 17),
                           quote_price=61.18, quote_ts=1792094400, shares_outstanding=374_920_000, shares_as_of=date(2026, 10, 15),
                           market_cap=47_045_770_703)
    assert s["text"].startswith("Vivmark Residential combined with AvalonBay Communities in a merger completed Aug 17, 2026. "
                                "Its company description on file predates the merger, so it is not shown.")
    assert "Equity Residential" not in s["text"] and "305 properties" not in s["text"]
    assert "worth about" not in s["text"]                     # 374.9M x $61.18 = $23B against a $47B market cap: left out
    assert "It's part of the S&P 500's Real Estate sector (REIT - Residential)." in s["text"]


def test_a_profile_written_after_the_merger_is_used():
    s = B.profile_sentence(name="Vivmark Residential", symbol="VMRK", short_description=EQR_TEXT, profile_filed=date(2026, 11, 5),
                           merged_name="AvalonBay Communities, Inc.", merged_on=date(2026, 8, 17))
    assert s["text"].startswith("Equity Residential is committed")


def test_market_value_needs_agreement_with_the_market_cap_on_file():
    assert B.market_value_agrees(61.18, 772_000_000, 47_045_770_703)
    assert not B.market_value_agrees(61.18, 374_920_000, 47_045_770_703)
    assert B.market_value_agrees(61.18, 374_920_000, None)            # nothing to compare: kept
    assert not B.market_value_agrees(None, 374_920_000, None)
    assert B.MARKET_VALUE_AGREEMENT == 0.25


def test_the_note_prompt_carries_the_merger():
    from types import SimpleNamespace
    from app.services.research_note_service import _build_generation_prompt
    t = SimpleNamespace(symbol="VMRK", name="Vivmark Residential", sector="Real Estate", industry="REIT - Residential", market_cap=47_045_770_703)
    event = "CORPORATE EVENT: AvalonBay Communities, Inc. merged into VMRK on 2026-08-17 (merged into VMRK on 2026-08-17). Describe the combined company as it is now.\n"
    p = _build_generation_prompt(t, None, None, [], event)
    assert "CORPORATE EVENT: AvalonBay Communities, Inc. merged into VMRK on 2026-08-17" in p
    assert "CORPORATE EVENT" not in _build_generation_prompt(t, None, None, [])
