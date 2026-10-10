"""The Discover headline guard (services/headline_guard): a headline beside a move must not contradict it, judged on the clauses
that name the stock."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services import headline_guard as G
from app.services import news as N

INTC = N.name_forms("INTC", "Intel Corporation")
CMG = N.name_forms("CMG", "Chipotle Mexican Grill, Inc.")


def test_a_verb_pointing_the_other_way_is_suppressed():
    assert G.check("Intel shares surge on foundry deal", -3.1, INTC).reason == "its verb says up on a down day"
    assert G.check("Intel plunges after guidance cut", 4.0, INTC).reason == "its verb says down on an up day"
    assert G.check("Intel announces new chip", -1.0, INTC).reason is None


def test_only_the_clause_naming_the_stock_counts():
    assert G.check("Starbucks Slides 3% as Chipotle Mexican Grill Jumps 5% on Takeover Talk", 6.2, CMG).reason is None
    assert G.check("Chipotle jumps on report Starbucks explored a takeover", -0.4, N.name_forms("SBUX", "Starbucks Corporation")).reason is None
    assert G.check("Intel Q3 revenue jumps 20%", -2.0, INTC).reason is None                 # a non-price figure
    assert G.check("Why Intel Plunged in September", 2.5, INTC).reason is None              # a longer period
    assert G.check("Intel Stock Is Up 212% Since December", -5.3, INTC).reason is None


def test_longer_periods_hedges_and_other_subjects_do_not_count():
    assert G.check("CPAY Stock Rises 14.6% in Three Months", -0.09, N.name_forms("CPAY", "Corpay, Inc.")).reason is None
    assert G.check("Goldman Sachs Falls 20% From Record High", 0.42, N.name_forms("GS", "The Goldman Sachs Group, Inc.")).reason is None
    assert G.check("Meta Stock Up 21% in One Month", -0.41, N.name_forms("META", "Meta Platforms, Inc.")).reason is None
    assert G.check("Jim Cramer Sees Little Relief for Home Depot (HD) Until Rates Fall", 1.97, N.name_forms("HD", "The Home Depot, Inc.")).reason is None
    assert G.check("PepsiCo Admits Its Soda Business Is Falling Behind Rivals", 3.73, N.name_forms("PEP", "PepsiCo, Inc.")).reason is None
    assert G.check("Why Micron (MU) Might be Well Poised for a Surge", -4.79, N.name_forms("MU", "Micron Technology, Inc.")).reason is None
    assert G.check("MU Stock Slides For Fourth Day", 4.06, N.name_forms("MU", "Micron Technology, Inc.")).reason.startswith("its verb says down")
    assert G.check("Humana Soars On Medicare Advantage Star Rating", -2.37, N.name_forms("HUM", "Humana Inc.")).reason.startswith("its verb says up")


def test_opinion_shows_nowhere_and_the_mover_slot_prefers_a_headline_explaining_the_move():
    t = datetime(2026, 10, 9, 15, tzinfo=timezone.utc)
    opinion = {"url": "c", "headline": "Intel Is Worth More Than Coca-Cola and PepsiCo Put Together", "source": "Yahoo", "published_at": t, "related": ["INTC"]}
    agreeing = {"url": "a", "headline": "Intel stock slides as chip stocks sell off", "source": "Yahoo", "published_at": t - timedelta(hours=2), "related": ["INTC"]}
    reuters = {"url": "r", "headline": "Intel names new foundry chief", "source": "Reuters", "published_at": t, "related": ["INTC"]}
    explainer = {"url": "e", "headline": "Why Intel Stock Slid Today", "source": "Yahoo", "published_at": t, "related": ["INTC"]}
    assert N.top_headline([opinion], "INTC", "Intel Corporation", None, None, -2.2) is None
    assert N.in_the_news([opinion], {"INTC": -2.2}, names={"INTC": "Intel Corporation"}) == []                     # nowhere on Discover
    assert N.top_headline([reuters, agreeing], "INTC", "Intel Corporation", None, None, -2.2)["url"] == "a"   # explains the move first
    assert N.top_headline([reuters, explainer], "INTC", "Intel Corporation", None, None, -2.2)["url"] == "e"  # an agreeing explainer is news
    assert N.top_headline([reuters], "INTC", "Intel Corporation", None, None, -2.2)["url"] == "r"


def test_a_stated_percent_must_match_the_printed_figure_within_one_and_a_half_points():
    assert G.check("Intel Slides 3% as Chip Stocks Sell Off", -3.9, INTC).reason is None
    assert G.check("Intel Slides 3% as Chip Stocks Sell Off", -5.3, INTC).reason.startswith("it states -3% against the -5.30% printed")
    assert G.check("Intel stock +5% premarket", -1.0, INTC).reason == "its stated move has the opposite sign"
    assert G.check("Intel stock falls 4%", None, INTC).reason is None
    assert G.check("SBA Communications (SBAC) Jumped, But What Is Driving Attention Now?", -2.0,
                   N.name_forms("SBAC", "SBA Communications Corporation")).reason == "its verb says up on a down day"   # "(SBAC)" is part of the name


def test_a_roundup_is_only_roundup_wording_and_a_group_shares_its_verb():
    assert N.is_roundup("Stocks making the biggest moves midday: T-Mobile, Verizon, AT&T, Crown Castle, Teva & more")
    assert N.is_roundup("These Stocks Are the Hidden Winners of SpaceX’s Spectrum Binge")
    assert not N.is_roundup("Verizon, AT&T, T-Mobile Stocks Slide as SpaceX Expands Wireless Ambitions")
    assert not N.is_roundup("BNTX, NVAX, MRNA Lead Vaccine Rally After Report Of An NIH Cancer-Vaccine Push")
    assert not N.is_roundup("Crown Castle Soars 13% as SpaceX’s $8 Billion Spectrum Buy Keeps Tower Build Option “Very Much Alive”")
    group = "Verizon, AT&T, T-Mobile Stocks Slide as SpaceX Expands Wireless Ambitions"
    for sym, name, move in (("VZ", "Verizon Communications Inc.", -10.14), ("T", "AT&T Inc.", -10.82), ("TMUS", "T-Mobile US, Inc.", -13.27)):
        assert G.agrees(group, move, N.name_forms(sym, name)), sym
        assert G.check(group, -move, N.name_forms(sym, name)).reason == "its verb says down on an up day", sym
    assert G.check("Novavax Soars 16%, Moderna Surges 11%, Merck Climbs 3%", 14.21, N.name_forms("MRNA", "Moderna, Inc.")).reason.startswith("it states +11%")
    story = {"headline": "Crown Castle Soars 13% as SpaceX Buy Keeps Tower Option Alive", "related": ["CCI", "AMT", "SBAC", "T", "VZ"],
             "published_at": datetime(2026, 10, 9, 15, tzinfo=timezone.utc), "url": "x", "source": "Yahoo"}
    assert N.headline_problem(story, "CCI", "Crown Castle Inc.", None, datetime(2026, 10, 8, 20, tzinfo=timezone.utc)) is None


def test_both_word_lists_live_in_one_file():
    root = Path(__file__).parents[1] / "app"
    for p in root.rglob("*.py"):
        if p.name != "headline_guard.py":
            src = p.read_text()
            assert "UP_VERBS =" not in src and "DOWN_VERBS =" not in src, p


def test_only_a_headline_that_would_have_shown_is_counted():
    t, t2 = datetime(2026, 10, 8, 18, tzinfo=timezone.utc), datetime(2026, 10, 8, 17, tzinfo=timezone.utc)
    stories = [{"url": "u1", "headline": "Intel stock falls 9% on foundry delay", "source": "Reuters", "published_at": t, "related": ["INTC"]},
               {"url": "u2", "headline": "Intel shares surge on chip news", "source": "Reuters", "published_at": t2, "related": ["INTC"]},
               {"url": "u3", "headline": "Intel stock falls 3% on chip glut worries", "source": "Yahoo", "published_at": t2, "related": ["INTC"]}]
    suppressed: dict = {}
    h = N.top_headline(stories, "INTC", "Intel Corporation", None, None, -3.4, suppressed)
    assert h["url"] == "u3"
    assert list(suppressed) == [("INTC", "u1")]                    # u2 was suppressed too, but would never have shown
    assert suppressed[("INTC", "u1")]["stated_pct"] == -9.0 and suppressed[("INTC", "u1")]["move_pct"] == -3.4
    suppressed = {}
    ranked = N.in_the_news(stories, {"INTC": -3.4}, per_ticker=1, names={"INTC": "Intel Corporation"}, moves={"INTC": -3.4}, suppressed=suppressed)
    assert [r["url"] for r in ranked] == ["u3"]
    assert list(suppressed) == [("INTC", "u1")]
    assert N.guard_share(1, 5) == 0.2 and N.guard_share(2, 5) > N.GUARD_WARN_SHARE and N.guard_share(1, 0) is None


@pytest.mark.asyncio
async def test_validate_judges_only_while_the_news_flag_is_on(monkeypatch):
    from app.config import settings
    from app.scripts.validate_data import PASS, check_news_headline_guard
    monkeypatch.setattr(settings, "discover_news_enabled", False)
    r = await check_news_headline_guard(None)
    assert r.level == PASS and "off" in r.message


def test_a_headline_counts_only_for_the_stock_it_leads_with():
    from datetime import date
    since = N.previous_session_close(date(2026, 10, 9))
    at = datetime(2026, 10, 9, 17, 0, tzinfo=timezone.utc)
    p = lambda h, sym, name: N.headline_problem({"headline": h, "source": "Yahoo", "published_at": at, "related": [sym], "url": h},
                                                sym, name, date(2026, 7, 1), since)
    lead = "does not lead with the company (not named in its first clause)"
    assert p("Stock Market Today, Oct. 9: AT&T Slides on SpaceX Spectrum Deal Threat", "T", "AT&T Inc.") is None   # wrap prefix skipped
    assert p("Stock Market Midday, Oct. 9: Stocks Edge Higher, Humana jumps 13%", "HUM", "Humana Inc.") == lead
    assert p("Apple Drops 3% on Reported iPhone 18 Pro Component Order Cuts; Skyworks Slips", "SWKS", "Skyworks Solutions, Inc.") == lead
    assert p("Zscaler Jumps 6% on Reaffirmed Revenue Outlook; Palo Alto and CrowdStrike Gain 4%", "PANW", "Palo Alto Networks, Inc.") == lead
    assert p("Intel Slides 3% as Chip Stocks Sell Off; NVIDIA and AMD Slip", "NVDA", "NVIDIA Corporation") == lead
    assert p("Verizon, AT&T, T-Mobile Stocks Slide as SpaceX Expands Wireless Ambitions", "TMUS", "T-Mobile US, Inc.") is None   # a list leads
    assert p("Big Tech Needs Power. Constellation Just Found a $1 Billion Buyer in Google.", "CEG", "Constellation Energy Corporation") == lead
    assert G.first_clause("U.S. Steel Jumps on Nippon Deal") == "U.S. Steel Jumps on Nippon Deal"
    assert N.is_roundup("Chevron's Venezuela Plan Will Pay Off, Says Analyst. Plus, Coinbase and 3 More Stocks.")


def test_every_move_word_is_a_direction_word_and_flat_words_contradict_a_big_move():
    NV, QC = N.name_forms("NVDA", "NVIDIA Corporation"), N.name_forms("QCOM", "QUALCOMM Incorporated")
    for w in ("slips", "slipped", "drops", "dropped", "tumbles", "sinks", "crashes", "edges lower", "trades down"):
        assert G.check(f"Nvidia {w} 2% on export curbs", 2.0, NV).reason == "its verb says down on an up day", w
    for w in ("gains", "gained", "climbs", "rises", "rose", "edges higher", "trades up"):
        assert G.check(f"Nvidia {w} 2% on China approval", -2.0, NV).reason == "its verb says up on a down day", w
    assert set(G.MOVE_WORDS) == set(G.UP_VERBS) | set(G.DOWN_VERBS) | set(G.ADVERBS)                    # one word list: the guard's
    assert G.check("Nvidia Gains Approval to Sell Chips in China", -2.0, NV).reason is None          # a verb taking an object
    assert G.check("Intel Steps Up Foundry Push", -3.0, INTC).reason is None                         # a phrasal verb, not a move
    flat = G.check("Skyworks Slips, Qualcomm Treads Water", 2.5, QC).reason
    assert flat.startswith("its words say flat") and G.check("Qualcomm Treads Water", -1.9, QC).reason is None
    assert G.check("Qualcomm shares little changed after report", -3.1, QC).reason.startswith("its words say flat")


def test_vs_is_opinion_only_when_it_compares_stocks():
    assert not G.is_opinion("Apple vs. Epic Ruling Lets Developers Link to Outside Payments")
    assert not G.is_opinion("FTC vs. Meta Trial Opens in Washington")
    assert G.is_opinion("Better Buy: Nvidia vs. AMD") and G.is_opinion("NVDA vs. AMD: Which Chip Stock Wins?")
    assert G.is_opinion("CrowdStrike vs. Palantir: one AI stock to own")
    assert G.is_opinion("Oracle vs. Cisco: The Dividend Battle Wall Street Didn't See Coming")            # company vs. company
    assert G.is_opinion("Coca-Cola versus PepsiCo: The Cola War Heats Up")
    assert not G.is_opinion("Apple vs. Epic: Supreme Court Declines Appeal")                           # legal news


def test_in_the_news_leaves_out_the_top_movers():
    now = datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc)
    st = lambda u, h, rel: {"url": u, "headline": h, "related": rel, "published_at": now, "source": "Yahoo"}
    stories = [st("1", "Verizon slides on SpaceX spectrum deal", ["VZ"]), st("2", "Skyworks slips on iPhone order cuts", ["SWKS"])]
    names = {"VZ": "Verizon Communications Inc.", "SWKS": "Skyworks Solutions, Inc."}
    out = N.in_the_news(stories, {"VZ": -10.1, "SWKS": -5.4}, names=names, exclude_symbols={"VZ"})
    assert [r["symbol"] for r in out] == ["SWKS"]
