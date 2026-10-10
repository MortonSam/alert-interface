"""Ivy's Discover sentences (services/ivy_moves): the check before anything shows, the no-news sentence, one rewrite then the
headline fallback, and a stored sentence matched to the stories she read."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

from app.services import ivy_moves as M

NOW = datetime(2026, 10, 9, 21, 0, tzinfo=timezone.utc)
SINCE = datetime(2026, 10, 8, 20, 0, tzinfo=timezone.utc)
st = lambda u, h, summary=None, mins=60, source="Yahoo": {"url": u, "headline": h, "summary": summary, "source": source,
                                                         "published_at": NOW - timedelta(minutes=mins), "related": []}
TMUS = [st("1", "SpaceX snaps up the 800 MHz spectrum T-Mobile dumped for $2.9 billion",
           "T-Mobile, Verizon and AT&T fell after SpaceX agreed to buy spectrum for Starlink Mobile."),
        st("2", "Stocks making the biggest moves midday: T-Mobile, Verizon, AT&T & more")]
check = lambda s, move=-13.27, inputs=TMUS: M.check_sentence(s, inputs, "TMUS", "T-Mobile US, Inc.", move)


def test_a_sentence_built_from_her_stories_passes():
    assert check("T-Mobile fell after SpaceX agreed to buy spectrum for Starlink Mobile, a new wireless rival.") == []
    assert check("T-Mobile fell 13.3% after SpaceX bought the 800 MHz spectrum for $2.9 billion.",
                 inputs=TMUS + [st("3", "T-Mobile falls 13.3% on SpaceX deal")]) == []


def test_an_invented_figure_fails():
    p = check("T-Mobile fell after SpaceX paid $4.1 billion for spectrum.")
    assert "the figure 4.1 appears in none of her stories" in p


def test_a_wrong_percent_for_the_stock_fails():
    p = check("T-Mobile fell 13% after SpaceX agreed to buy spectrum.", inputs=TMUS + [st("3", "T-Mobile falls 13% on SpaceX deal")])
    assert p == ["it states -13% for the stock against the printed -13.27%"]
    assert any(x.startswith("the figure 9.5") for x in check("T-Mobile fell 9.5% after SpaceX agreed to buy spectrum."))


def test_an_unnamed_company_or_person_fails():
    assert "the name Amazon appears in none of her stories" in check("T-Mobile fell after Amazon and SpaceX bought spectrum.")
    assert "the name Musk appears in none of her stories" in check("T-Mobile fell after Elon Musk's SpaceX bought spectrum.")


def test_advice_prediction_and_opinion_wording_fail():
    for s, word in [("T-Mobile fell after SpaceX bought spectrum, so investors should sell.", "should"),
                    ("T-Mobile fell after SpaceX bought spectrum and could fall further.", "could"),
                    ("T-Mobile fell after SpaceX bought spectrum, making it a buy.", "buy"),
                    ("T-Mobile fell after SpaceX bought spectrum, leaving it undervalued.", "undervalued"),
                    ("T-Mobile fell after SpaceX bought spectrum and will face a new rival.", "will")]:
        assert any(word in x for x in check(s) if x.startswith("advice")), s
    assert check("T-Mobile fell in a sell-off after SpaceX bought spectrum.") == []                      # a sell-off is the move
    assert check("T-Mobile fell after better-than-expected interest in SpaceX's spectrum for Starlink Mobile.") == []


def test_length_and_one_sentence():
    long = "T-Mobile fell after SpaceX agreed to buy spectrum for Starlink Mobile " + "and T-Mobile fell " * 5 + "."
    assert any(x.endswith(f"more than {M.MAX_WORDS}") for x in check(long))
    assert "more than one sentence" in check("T-Mobile fell. SpaceX bought spectrum.")


class FakeClient:
    """Returns the queued generations in order; every verification is "supported" unless told otherwise."""
    def __init__(self, generations, verdict="supported"):
        self.generations, self.verdict, self.calls = list(generations), verdict, []

    async def generate_answer(self, prompt, max_tokens=300):
        self.calls.append(prompt)
        return {"content": self.generations.pop(0), "model_used": "claude-sonnet-4-6", "input_tokens": 1000, "output_tokens": 50}

    async def verify_research_note(self, prompt):
        return {"content": json.dumps({"status": self.verdict, "evidence": "x"}), "model_used": "claude-opus-4-6", "input_tokens": 800, "output_tokens": 40}


def run(coro):
    return asyncio.run(coro)


def test_no_stored_story_means_the_exact_no_news_sentence_without_a_model_call():
    client = FakeClient([])
    out = run(M.explain("HPQ", "HP Inc.", -6.91, [], client=client))
    assert out["result"] == "no_news" and out["sentence"] == "No reported news explains this move." == M.NO_NEWS and client.calls == []
    out = run(M.explain("TMUS", "T-Mobile US, Inc.", -13.27, TMUS, client=FakeClient([json.dumps({"sentence": "NONE", "sources": []})])))
    assert (out["result"], out["sentence"]) == ("no_news", M.NO_NEWS)


def test_she_rewrites_once_then_the_row_falls_back_with_the_reasons_stored():
    bad = json.dumps({"sentence": "T-Mobile fell after Amazon bought spectrum.", "sources": [1]})
    good = json.dumps({"sentence": "T-Mobile fell after SpaceX agreed to buy spectrum for Starlink Mobile.", "sources": [1, 2]})
    out = run(M.explain("TMUS", "T-Mobile US, Inc.", -13.27, TMUS, client=FakeClient([bad, good])))
    assert out["result"] == "passed" and out["attempts"] == 2 and [s["url"] for s in out["sources"]] == ["1", "2"]
    assert "the name Amazon appears in none of her stories" in out["problems"][0]["reasons"]
    out = run(M.explain("TMUS", "T-Mobile US, Inc.", -13.27, TMUS, client=FakeClient([bad, bad])))
    assert out["result"] == "fallback" and out["sentence"] is None and len(out["problems"]) == 2
    out = run(M.explain("TMUS", "T-Mobile US, Inc.", -13.27, TMUS, client=FakeClient([good, good], verdict="unsupported")))
    assert out["result"] == "fallback" and out["problems"][0]["reasons"][0].startswith("the verifier marked it unsupported")
    assert out["cost_usd"] > 0


def test_her_inputs_include_roundups_and_a_story_naming_her_only_in_its_summary_and_the_fingerprint_follows_them():
    other = st("9", "Verizon slides on SpaceX deal", "Verizon, AT&T and T-Mobile all fell.")
    old = st("8", "T-Mobile falls", mins=60 * 30)
    inputs = M.input_stories(TMUS + [other, old, st("7", "Apple gains")], "TMUS", "T-Mobile US, Inc.", SINCE)
    assert [s["url"] for s in inputs] == ["1", "2", "9"]                      # the roundup and the summary mention count; the old one does not
    fp = M.fingerprint("TMUS", inputs)
    assert fp == M.fingerprint("TMUS", list(reversed(inputs)))
    assert fp != M.fingerprint("TMUS", inputs[:2])


def test_a_stored_sentence_shows_only_while_its_percent_matches_the_printed_change():
    note = {"result": "passed", "sentence": "T-Mobile fell 13.3% after SpaceX bought spectrum."}
    assert M.display_ok(note, -13.27, "TMUS", "T-Mobile US, Inc.")
    assert not M.display_ok(note, -12.1, "TMUS", "T-Mobile US, Inc.")
    assert M.display_ok({"result": "no_news", "sentence": None}, -12.1, "TMUS", None)
    assert not M.display_ok({"result": "fallback", "sentence": None}, -12.1, "TMUS", None)


def test_the_sentence_step_runs_only_behind_the_news_flag_and_validate_reads_its_run():
    from pathlib import Path
    src = (Path(__file__).parents[1] / "app" / "scripts" / "refresh_news.py").read_text()
    assert "if exit_code == 0 and settings.discover_news_enabled:" in src
    from app.scripts.validate_data import CHECKS, check_ivy_sentences
    assert check_ivy_sentences in CHECKS and M.FALLBACK_WARN_SHARE == 0.2


def test_the_check_reads_names_and_ratings_as_reported():
    inputs = [st("1", "Goldman Sachs upgrades Palantir to Buy on AI demand", "SBA Communications and other tower stocks rose; Circle backed OKX at a $25B valuation.")]
    p = lambda s, sym="PLTR", name="Palantir Technologies Inc.", move=5.17: M.check_sentence(s, inputs, sym, name, move)
    assert p("Goldman Sachs upgraded Palantir to Buy, citing AI demand.") == []                   # an analyst's action, reported
    assert p("Palantir rose on AI-related demand after Goldman Sachs upgraded it.") == []
    assert p("Investor interest rose after Goldman Sachs upgraded Palantir.") == []
    assert p("Coinbase rose after Circle backed OKX at a $25B valuation.", "COIN", "Coinbase Global, Inc.", 4.3) == []
    assert p("SBA Communications' shares rose with other tower stocks.", "SBAC", "SBA Communications Corporation", 7.34) == []


def test_a_model_that_reconsiders_is_read_from_its_last_answer():
    raw = '{"sentence": "AMT jumped after a rate cut.", "sources": [2]}\n\nWait, I need to re-examine.\n\n{"sentence": "NONE", "sources": []}'
    assert M.parse_output(raw) == ("NONE", [])
    assert M.parse_output("no json here") == ("", [])
    assert M.parse_verdict('Here is my check: {"status": "supported", "evidence": "story 1"}') == ("supported", "story 1")


def test_a_percent_counts_as_the_stocks_unless_its_clause_names_another_company():
    inputs = [st("1", "Why SBA Communications (SBAC) Is Up 15.1% After SpaceX's $8 Billion Spectrum Deal", "Circle shares spiked 7% after the deal.")]
    p = lambda s, move=7.34: M.check_sentence(s, inputs, "SBAC", "SBA Communications Corporation", move)
    assert "it states +15.1% for the stock against the printed +7.34%" in p("Investors linked SBAC's rise to SpaceX's $8 billion spectrum deal, which sent the stock up 15.1%.")
    assert not [x for x in p("SBAC rose with tower stocks after SpaceX's $8 billion spectrum deal, while Circle shares spiked 7%.") if x.startswith("it states")]


def test_a_sentence_that_only_restates_the_move_is_no_news():
    assert M.explains_nothing("HP stock dropped despite broader market gains, standing out as a notable decliner on the day.", "HPQ", "HP Inc.")
    assert M.explains_nothing("Deere stock sank even as the broader market gained.", "DE", "Deere & Company")
    assert not M.explains_nothing("Cboe rallied after Morgan Stanley issued a double upgrade.", "CBOE", "Cboe Global Markets, Inc.")
    out = run(M.explain("HPQ", "HP Inc.", -6.91, [st("1", "HP (HPQ) Stock Drops Despite Market Gains: Important Facts to Note")],
                        client=FakeClient([json.dumps({"sentence": "HP stock dropped despite broader market gains.", "sources": [1]})])))
    assert (out["result"], out["sentence"]) == ("no_news", M.NO_NEWS)


def test_an_analysts_upside_is_a_prediction():
    inputs = [st("1", "Goldman Sachs Upgrades Palantir to Buy, Sees 18% Upside")]
    p = M.check_sentence("Goldman Sachs upgraded Palantir to Buy, seeing 18% upside.", inputs, "PLTR", "Palantir Technologies Inc.", 5.17)
    assert any("upside" in x for x in p if x.startswith("advice"))


def test_the_linked_source_never_contradicts_the_printed_change_and_cramer_is_opinion():
    sources = [{"headline": "Circle Internet Spikes 7% After Backing OKX; Coinbase Rallies 6%", "url": "a"},
               {"headline": "COIN, HOOD Stocks Get Price Target Hikes", "url": "b"}]
    assert M.lead_index(sources, 4.30, "COIN", "Coinbase Global, Inc.") == 1
    assert M.lead_index(sources[:1], 4.30, "COIN", "Coinbase Global, Inc.") is None
    inputs = [st("1", "Jim Cramer Says HPE Has Finally Turned a Corner")]
    assert any("cramer" in x for x in M.check_sentence("HPE rose as Jim Cramer said it turned a corner.", inputs, "HPE", "Hewlett Packard Enterprise Company", 3.46))


# ── regressions from the Oct 9 replay ──
COIN_STORIES = [st("1", "Circle Internet Spikes 7% After Backing OKX at $25B Valuation; Coinbase Rallies 6%"),
                st("2", "President Trump Discloses New Trades in Strategy (MSTR), Coinbase, NVIDIA, SpaceX, Meta",
                   "President Trump disclosed purchasing Coinbase shares in new ethics filings.")]


def test_an_event_that_merely_happened_the_same_day_is_not_a_cause():                       # COIN, Oct 9
    s = "Coinbase rallied after Circle Internet backed OKX, and President Trump disclosed purchasing Coinbase shares in new ethics filings."
    p = M.cause_problems(s, COIN_STORIES, "COIN", "Coinbase Global, Inc.")
    assert "President appears in no source that says it moved Coinbase Global" in p and "Trump appears in no source that says it moved Coinbase Global" in p
    assert M.cause_problems("Coinbase rallied after Circle Internet backed OKX.", COIN_STORIES, "COIN", "Coinbase Global, Inc.") == []
    assert M.cause_problems("Coinbase rose as President Trump disclosed trades.", COIN_STORIES[1:], "COIN", "Coinbase Global, Inc.") == \
        ["none of her sources says an event moved Coinbase Global"]
    assert "an event that merely happened the same day" in M.build_verification_prompt("COIN", "Coinbase Global, Inc.", s, COIN_STORIES)


def test_momentum_is_opinion():                                                               # TWLO, Oct 9
    inputs = [st("1", "Twilio (TWLO) Stock Trades Up, Here Is Why", "JPMorgan raised its price target; Twilio joined the S&P 500.")]
    p = M.check_sentence("JPMorgan raised its price target on Twilio, and institutional buying tied to its S&P 500 addition added further momentum.",
                         inputs, "TWLO", "Twilio Inc.", 4.97)
    assert any("momentum" in x for x in p if x.startswith("advice"))


def test_she_names_the_company_by_its_name():                                                 # AMT and SBAC, Oct 9
    amt = [st("1", "Why American Tower Stock Jumped 8.6% Today", "Cell tower stocks rose after a SpaceX spectrum deal.")]
    assert "it does not name American Tower by its name" in M.check_sentence(
        "A SpaceX spectrum deal sparked expectations of a terrestrial tower build, sending cell tower stocks sharply higher.", amt, "AMT", "American Tower Corporation", 9.30)
    sbac = [st("1", "SBA Communications (SBAC) Jumped, But What Is Driving Attention Now?", "SpaceX agreed to buy spectrum for $8 billion.")]
    assert "it does not name SBA Communications by its name" in M.check_sentence(
        "SpaceX agreed to buy spectrum for $8 billion, sparking interest in tower owners like SBAC as possible future SpaceX tower hosts.", sbac, "SBAC", "SBA Communications Corporation", 7.34)
    assert M.check_sentence("SBA Communications rose after SpaceX agreed to buy spectrum for $8 billion.", sbac, "SBAC", "SBA Communications Corporation", 7.34) == []


def test_a_row_that_falls_back_with_no_headline_says_ivy_could_not_confirm():
    assert M.CANNOT_CONFIRM == "Ivy couldn't confirm what moved this stock."
    from pathlib import Path
    src = (Path(__file__).parents[1] / "app" / "routers" / "discover_news.py").read_text()
    assert "if m.ivy is None and m.headline is None:" in src and 'IvyLine(sentence=CANNOT_CONFIRM, result="unconfirmed")' in src


def test_links_land_on_the_article_or_the_story_is_not_shown():
    from app.services import news_links as L
    assert L.classify("https://finance.yahoo.com/markets/stocks/articles/x.html", 200, "<div class='premium-paywall-subheading'>Upgrade to read this MT Newswires article</div>") == "paywall"
    yahoo_free = "<style>.premium-paywall-gradient.yf-v6n2s3{content:''}</style><script>enableGPaywallDataStructure</script><p>" + "Article text. " * 400 + "</p>"
    assert L.classify("https://finance.yahoo.com/markets/stocks/articles/x.html", 200, yahoo_free) == "ok"      # a class name in the stylesheet is no paywall
    assert L.classify("https://www.fool.com/investing/x/", 200, "<script src='recaptcha.js'></script><p>" + "Story. " * 800 + "</p>") == "ok"
    assert L.classify("https://www.thestreet.com/investing/x", 403, "Access Denied") == "unchecked"
    assert L.classify("https://www.barchart.com/story/news/1/x", 202, "window.awsWafCookieDomainList = ['barchart.com'];") == "unchecked"
    assert L.classify("https://www.wsj.com/articles/x", 200, "") == "paywall"
    assert L.classify("https://example.com/login?next=/x", 200, "") == "login"
    assert L.classify("https://finnhub.io/api/news?id=abc", 200, "") == "broken" and L.classify(None, None, "") == "broken"
    from app.services import news as N
    from datetime import date
    story = lambda state: {"headline": "Intel slides as chip stocks sell off", "source": "Yahoo", "published_at": NOW, "related": ["INTC"], "url": "u", "link_state": state}
    p = lambda state: N.headline_problem(story(state), "INTC", "Intel Corporation", date(2026, 7, 23), SINCE)
    assert p("ok") is None and p("unchecked") is None
    assert p("paywall") == "its link lands on a paywall page" and p("login") == "its link lands on a login page"
    assert p(None) == "its link is not resolved to the article yet" and p("broken") == "its link is broken"
    srcs = [{"headline": "Intel slides", "url": "a", "link": "https://x/a", "link_state": "paywall"},
            {"headline": "Intel cuts jobs", "url": "b", "link": "https://x/b", "link_state": "ok"}]
    assert M.lead_index(srcs, -5.0, "INTC", "Intel Corporation") == 1


def test_her_linked_source_is_never_a_roundup_and_suffixes_are_not_names():
    srcs = [{"headline": "These Stocks Are the Hidden Winners of SpaceX's Spectrum Binge", "url": "a"},
            {"headline": "Crown Castle Rises After SpaceX Spectrum Deal", "url": "b"}]
    assert M.lead_index(srcs, 15.6, "CCI", "Crown Castle Inc.") == 1
    inputs = [st("1", "Verizon falls after SpaceX buys 800 MHz spectrum")]
    assert M.check_sentence("Verizon Communications Inc. fell after SpaceX bought 800 MHz spectrum.", inputs, "VZ", "Verizon Communications Inc.", -10.14) == []
