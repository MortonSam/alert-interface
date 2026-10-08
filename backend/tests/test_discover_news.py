"""Discover news (services/news): dedupe and the 24-hour window, movers from the newest session, a company's headline only when it
names the company, "In the news" ranked by the move then recency, and fail-closed visibility."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services import news as N

NOW = datetime(2026, 10, 8, 18, 0, tzinfo=timezone.utc)
UNI = {"MU", "KO", "PEP", "INTC", "AMD", "HD", "XOM"}


def item(url, headline, minutes_ago, related="", source="Yahoo"):
    return {"url": url, "headline": headline, "datetime": int((NOW - timedelta(minutes=minutes_ago)).timestamp()), "related": related, "source": source}


def test_dedupe_keeps_one_story_per_url_and_headline_within_a_day_and_merges_tickers():
    raw = [("company", item("u1", "Micron  beats", 30, "MU")), ("company", item("u1", "Micron beats", 30, "AMD,ZZZ")),
           ("company", item("u2", "Micron beats", 30, "INTC")),                                  # same headline and source, another URL
           ("general", item("u3", "Markets wrap", 60)), ("company", item("u4", "Old news", 25 * 60, "MU")),
           ("company", item("u5", "Future", -60, "MU")), ("company", item("", "No url", 5, "MU"))]
    out = N.dedupe(raw, NOW, UNI)
    assert set(out) == {"u1", "u3"}
    assert out["u1"]["related"] == ["AMD", "INTC", "MU"] and out["u1"]["headline"] == "Micron beats" and out["u3"]["category"] == "general"


def test_movers_come_from_the_newest_session_only():
    t = lambda h: NOW - timedelta(hours=h)
    quotes = [{"symbol": s, "name": None, "price": 10.0, "change_pct": c, "quote_time": t(1)} for s, c in
              [("A1", 5), ("A2", 4), ("A3", 3), ("A4", 2), ("A5", 1), ("A6", 0.5), ("B1", -6), ("B2", -1)]]
    quotes.append({"symbol": "OLD", "name": None, "price": 10.0, "change_pct": 30.0, "quote_time": t(30)})   # yesterday's last trade
    up, down = N.movers(quotes)
    assert [q["symbol"] for q in up] == ["A1", "A2", "A3", "A4", "A5"] and [q["symbol"] for q in down] == ["B1", "B2"]


def test_a_headline_counts_for_a_company_only_when_it_names_it():
    assert N.names_company("Micron Could Be Poised for a Major Breakout", "MU", "Micron Technology, Inc.")
    assert N.names_company("Home Depot Stock Is Down 17% in 2026", "HD", "The Home Depot, Inc.")
    assert N.names_company("How XOM's Strong Balance Sheet Helps", "XOM", "Exxon Mobil Corporation")
    assert not N.names_company("PepsiCo cuts guidance: what these red flags say", "KO", "The Coca-Cola Company")
    assert not N.names_company("It is a good day to buy", "IT", "Gartner, Inc.") and not N.names_company("ko and pep", "KO", None)
    stories = [{"headline": "PepsiCo cuts guidance", "related": ["KO", "PEP"], "published_at": NOW, "url": "a", "source": None},
               {"headline": "Coca-Cola raises its dividend", "related": ["KO"], "published_at": NOW - timedelta(hours=2), "url": "b", "source": None},
               {"headline": "These Dow stocks are moving: Coca-Cola, Intel, AMD, Micron", "related": ["KO", "INTC", "AMD", "MU"], "published_at": NOW, "url": "c", "source": None}]
    assert N.top_headline(stories, "KO", "The Coca-Cola Company")["url"] == "b"           # newest that names KO and is not a roundup
    assert N.top_headline(stories[:1], "KO", "The Coca-Cola Company") is None             # no such story: no headline


def test_in_the_news_ranks_by_the_named_stocks_move_then_recency_two_per_stock():
    s = lambda u, h, rel, mins: {"url": u, "headline": h, "related": rel, "published_at": NOW - timedelta(minutes=mins), "source": "Yahoo"}
    stories = [s("1", "Intel slides", ["INTC"], 50), s("2", "Intel and AMD slip", ["INTC", "AMD"], 10), s("3", "Is AMD stock worth it", ["INTC", "AMD"], 5),
               s("4", "Intel third story", ["INTC"], 1), s("5", "Micron breakout", ["MU"], 30), s("6", "Unrelated", ["MU"], 2)]
    names = {"INTC": "Intel Corporation", "AMD": "Advanced Micro Devices, Inc.", "MU": "Micron Technology, Inc."}
    out = N.in_the_news(stories, {"INTC": -6.6, "AMD": -4.4, "MU": -4.6}, names=names)
    assert [(r["url"], r["symbol"]) for r in out] == [("4", "INTC"), ("2", "INTC"), ("5", "MU"), ("3", "AMD")]   # "Is AMD stock" goes under AMD


def test_the_sections_fail_closed():
    fresh = NOW - timedelta(hours=1)
    assert N.visibility(fresh, 0, NOW, fresh).visible
    assert N.visibility(fresh, None, NOW, fresh).visible
    assert N.visibility(fresh, 1, NOW, fresh).reason == "the news step's last run failed"
    assert N.visibility(NOW - timedelta(hours=25), 0, NOW, fresh).reason == "the newest story is more than 24 hours old"
    assert N.visibility(None, 0, NOW, fresh).reason == "no stories stored"
    assert N.visibility(fresh, 0, NOW, NOW - timedelta(hours=30)).reason == "no quote snapshot from the last 24 hours"


def test_the_route_is_gated_and_the_copy_never_says_because():
    src = (Path(__file__).parent.parent / "app" / "routers" / "discover_news.py").read_text()
    assert "if not (settings.discover_news_enabled or admin):" in src
    from app.config import Settings
    assert Settings.model_fields["discover_news_enabled"].default is False
    from app.scripts.validate_data import CHECKS, check_news_freshness
    assert check_news_freshness in CHECKS
    from app.startup import news_run_due
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    assert news_run_due(datetime(2026, 10, 8, 10, 0, tzinfo=ny), None)
    assert not news_run_due(datetime(2026, 10, 8, 10, 30, tzinfo=ny), datetime(2026, 10, 8, 10, 0, tzinfo=ny))
    assert not news_run_due(datetime(2026, 10, 10, 10, 0, tzinfo=ny), None) and not news_run_due(datetime(2026, 10, 8, 20, 0, tzinfo=ny), None)


def test_headline_rules_established_first_no_templates_no_other_quarters_and_after_the_previous_close():
    from datetime import date
    since = N.previous_session_close(date(2026, 10, 8))
    assert since == datetime(2026, 10, 7, 16, 0, tzinfo=N.NEW_YORK)
    assert N.previous_session_close(date(2026, 10, 12)) == datetime(2026, 10, 9, 16, 0, tzinfo=N.NEW_YORK)   # Monday: Friday's close
    t = lambda h: datetime(2026, 10, 8, h, 0, tzinfo=N.NEW_YORK)
    st = lambda h, src, hr, rel=("INTC",): {"headline": h, "source": src, "published_at": hr, "related": list(rel), "url": h}
    p = lambda s, last=date(2026, 7, 23): N.headline_problem(s, "INTC", "Intel Corporation", last, since)
    assert p(st("Intel (INTC): Buy, Sell, or Hold Post Q2 Earnings?", "Yahoo", t(13))) == "a question or template headline"
    assert p(st("Should You Buy Intel Stock Now", "Yahoo", t(13))) == "a question or template headline"
    assert p(st("Intel Among Stocks to Watch Today", "Yahoo", t(13))) == "a question or template headline"
    assert p(st("Is It Time to Sell Intel", "Yahoo", t(13))) == "a question or template headline"
    assert p(st("Intel earnings preview: what to expect", "Yahoo", t(13))) == "about an upcoming report, not the latest one"
    assert p(st("Intel second-quarter results beat", "Yahoo", t(13))).startswith("names an earnings quarter but is not from the 14 days after")
    assert p(st("Intel second-quarter results beat", "Yahoo", t(13)), date(2026, 10, 1)) is None              # one week after the report
    assert p(st("Intel slides as chip stocks sell off", "Yahoo", datetime(2026, 10, 7, 15, 59, tzinfo=N.NEW_YORK))) == "published before the previous session's close"
    assert p(st("Intel slides as chip stocks sell off", "Yahoo", t(9))) is None
    stories = [st("Intel slides as chip stocks sell off", "Yahoo", t(13)), st("Intel cuts jobs in Oregon", "Reuters", t(9)),
               st("Intel (INTC): Buy, Sell, or Hold?", "CNBC", t(14))]
    assert N.top_headline(stories, "INTC", "Intel Corporation", date(2026, 7, 23), since)["source"] == "Reuters"   # established first, then newest
    assert N.source_tier("Reuters") == 0 and N.source_tier("CNBC") == 0 and N.source_tier("Yahoo") == 1 and N.source_tier(None) == 1
    out = N.in_the_news(stories, {"INTC": -5.3}, names={"INTC": "Intel Corporation"}, last_reports={"INTC": date(2026, 7, 23)}, since=since)
    assert [r["source"] for r in out] == ["Yahoo", "Reuters"]                                                  # by move, then recency; the template is out
