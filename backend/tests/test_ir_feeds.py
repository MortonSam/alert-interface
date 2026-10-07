"""Press-release feeds as a confirmation source: item parsing (titles-only Q4 feeds and Atom), which titles are announcements,
the issuer rule, reading the date from the linked release, the evidence and its link, which feeds the calendar reads, the
discovery's classification of /feed hits, and the digest's seven-night spot-check list."""
from datetime import date

from app.scripts.discover_ir_feeds import UNREVIEWED, classification_for
from app.scripts.refresh_earnings_calendar import IR_FEED_WINDOW_DAYS, feed_targets
from app.services import ir_feeds as F
from app.services.notify import digest_message, feed_spotcheck_active

T = date(2026, 10, 6)
Q4_FEED = """<?xml version="1.0"?><rss><channel><title>Cadence</title>
<item><title>Cadence Announces Third Quarter 2026 Financial Results Webcast</title><link>https://investor.cadence.com/news/q3-webcast</link><pubDate>Mon, 05 Oct 2026 16:15:00 GMT</pubDate></item>
<item><title>Cadence Reports Second Quarter 2026 Financial Results</title><link>https://investor.cadence.com/news/q2-results</link><pubDate>Mon, 27 Jul 2026 16:05:00 GMT</pubDate></item>
<item><title>Cadence Declares Quarterly Dividend</title><link>https://investor.cadence.com/news/div</link><pubDate>Mon, 20 Jul 2026 16:05:00 GMT</pubDate></item>
<item><title>Cadence Design Systems Foundation Announces Third Quarter 2026 Grant Results Webcast</title><link>https://investor.cadence.com/news/foundation</link><pubDate>Mon, 13 Jul 2026 16:05:00 GMT</pubDate></item>
</channel></rss>"""
ATOM_FEED = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Acme Corp to Report Third Quarter Results on October 28, 2026</title>
<link href="/news/acme-q3"/><summary>Acme Corp will release its third quarter results on Wednesday, October 28, 2026, after the market closes.</summary><updated>2026-10-01T12:00:00Z</updated></entry></feed>"""
RELEASE_PAGE = """<html><body><script>var x = 1;</script><h1>Cadence Announces Third Quarter 2026 Financial Results Webcast</h1>
<p>SAN JOSE, Calif., Oct. 5, 2026 -- Cadence Design Systems, Inc. (Nasdaq: CDNS) will report its third quarter 2026 financial results on Monday, October 26, 2026, after the market closes. The results cover the quarter ended September 27, 2026.</p></body></html>"""


def test_parse_items_reads_titles_only_feeds_and_atom_entries():
    items = F.parse_items(Q4_FEED, "https://investor.cadence.com/rss/pressrelease.aspx")
    assert [i["title"][:16] for i in items] == ["Cadence Announce", "Cadence Reports ", "Cadence Declares", "Cadence Design S"]
    assert items[0]["link"] == "https://investor.cadence.com/news/q3-webcast" and items[0]["published"].startswith("Mon, 05 Oct 2026")
    atom = F.parse_items(ATOM_FEED, "https://ir.acme.com/feed.atom")
    assert atom[0]["link"] == "https://ir.acme.com/news/acme-q3" and "after the market closes" in atom[0]["text"]


def test_only_announcement_titles_naming_the_issuer_are_followed():
    items = F.parse_items(Q4_FEED)
    assert F.looks_like_announcement(items[0]["title"]) and not F.looks_like_announcement(items[1]["title"]) and not F.looks_like_announcement(items[2]["title"])
    assert F.looks_like_announcement("Quest Diagnostics to Release Third Quarter Financial Results on October 22, 2026")
    assert F.looks_like_announcement("Huntington Bancshares Incorporated Announces Third Quarter 2026 Earnings Call Details")
    assert not F.looks_like_announcement("NVIDIA Announces Financial Results for Second Quarter Fiscal 2027")
    picked = F.candidates(items, "Cadence Design Systems, Inc.", "CDNS")
    assert [c["title"][:30] for c in picked] == ["Cadence Announces Third Quarte"]          # the Foundation's release names someone else
    assert F.names_company("ADP to Announce First Quarter Fiscal 2027 Financial Results", "Automatic Data Processing, Inc.", "ADP")   # the symbol on its own feed
    assert not F.names_company("CDNSX Partners to Announce Results", "Cadence Design Systems, Inc.", "CDNS")


def test_the_date_is_read_from_the_feed_text_or_the_linked_release_with_the_item_as_evidence():
    items = F.parse_items(Q4_FEED, "https://investor.cadence.com/rss/pressrelease.aspx")
    assert F.announcement_from_items(items, {}, "Cadence Design Systems, Inc.", T) is None                  # titles only: nothing yet
    pages = {"https://investor.cadence.com/news/q3-webcast": F.clean(RELEASE_PAGE)}
    hit = F.announcement_from_items(items, pages, "Cadence Design Systems, Inc.", T)
    assert hit.day == date(2026, 10, 26) and hit.timing == "amc"                                            # the period date Sep 27 is never the results date
    assert hit.evidence.startswith("press release via IR feed Mon, 05 Oct 2026 16:15:00: Cadence Announces Third Quarter 2026 Financial Results Webcast")
    assert F.release_link(hit.evidence) == "https://investor.cadence.com/news/q3-webcast"
    assert F.is_feed_evidence("confirmed: " + hit.evidence)
    atom = F.announcement_from_items(F.parse_items(ATOM_FEED, "https://ir.acme.com/feed.atom"), {}, "Acme Corp", T)
    assert atom.day == date(2026, 10, 28)                                                                   # the title names the date; timing comes from the sentence that does


def test_feed_targets_are_readable_feeds_with_a_date_inside_the_window():
    feeds = {"CDNS": "u1", "FAR": "u2", "NOFEED": None}
    feeds = {k: v for k, v in feeds.items() if v}
    fin = {"CDNS": {date(2026, 10, 26): "amc"}, "FAR": {T.fromordinal(T.toordinal() + IR_FEED_WINDOW_DAYS + 1): "amc"}, "NOFEED": {date(2026, 10, 20): "bmo"}}
    assert feed_targets(["CDNS", "FAR", "NOFEED"], fin, {}, {}, T, feeds) == {"CDNS": "u1"}


def test_discovery_classifies_a_site_wide_feed_as_unreviewed_and_an_ir_path_as_press_releases():
    assert classification_for("https://investors.micron.com/rss/pressrelease.aspx") == F.PRESS_RELEASES
    assert classification_for("https://apacorp.com/feed") == UNREVIEWED
    assert classification_for(None) is None


def test_robots_rule_requires_both_our_agent_and_everyone():
    from urllib import robotparser
    rp = robotparser.RobotFileParser(); rp.parse(["User-agent: *", "Disallow: /news/"])
    assert not F.allowed(rp, "https://x.com/news/q3") and F.allowed(rp, "https://x.com/rss/pressrelease.aspx")


def test_digest_lists_feed_confirmations_for_seven_nights_with_links():
    confs = [{"symbol": "CDNS", "date": "2026-10-26", "link": "https://investor.cadence.com/news/q3-webcast", "title": "Cadence Announces..."}]
    assert feed_spotcheck_active("2026-10-06", date(2026, 10, 6)) and feed_spotcheck_active("2026-10-06", date(2026, 10, 12))
    assert not feed_spotcheck_active("2026-10-06", date(2026, 10, 13)) and not feed_spotcheck_active(None, T)
    _, body = digest_message("2026-10-07", 30, 30, [], None, 90.0, None, None, confs)
    assert "IR-feed confirmations to spot-check (1): CDNS 2026-10-26 https://investor.cadence.com/news/q3-webcast" in body
    _, body = digest_message("2026-10-07", 30, 30, [], None, 90.0, None, None, None)
    assert "spot-check" not in body


EVENTS_FEED = """<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>FedEx Events </title><lastBuildDate>Wed, 28 Oct 2026 16:30:00 -0400</lastBuildDate>
<item><title>10/28/2026 : FedEx Q3 2026 Earnings Call</title><link>https://investors.fedex.com/news-and-events/upcoming-events/upcoming-events-details/2026/FedEx-Earnings-Call/default.aspx</link><pubDate>Mon, 21 Sep 2026 08:00:39 -0400</pubDate></item>
<item><title>2/2/2027 : FedEx Q4 2026 Earnings Call</title><link>https://investors.fedex.com/x/q4</link><pubDate>Tue, 23 Jun 2026 22:20:34 -0400</pubDate></item>
<item><title>11/5/2026 : FedEx Annual Meeting of Shareholders</title><link>https://investors.fedex.com/x/agm</link></item>
</channel></rss>"""
ARCH_EVENTS = """<rss><channel><lastBuildDate>Tue, 27 Oct 2026 16:00:00 -0400</lastBuildDate>
<item><title>10/27/2026 : Q3 2026 Earnings Release</title><link>https://ir.archgroup.com/x/release</link></item>
<item><title>10/28/2026 : Q3 2026 Earnings Conference Call</title><link>https://ir.archgroup.com/x/call</link></item></channel></rss>"""


def test_the_q4_events_feed_confirms_a_scheduled_earnings_call_or_release():
    assert F.events_feed_url("https://investors.fedex.com/rss/pressrelease.aspx") == "https://investors.fedex.com/rss/event.aspx"
    assert F.events_feed_url("https://ir.acme.com/feed.atom") is None and F.events_feed_url(None) is None
    ev = F.earnings_events(F.parse_items(EVENTS_FEED, ""), T)
    assert [(e["day"].isoformat(), e["title"]) for e in ev] == [("2026-10-28", "FedEx Q3 2026 Earnings Call"), ("2027-02-02", "FedEx Q4 2026 Earnings Call")]   # the annual meeting is not one
    a = F.announcement_from_events(EVENTS_FEED, T)
    assert a.day == date(2026, 10, 28) and a.timing == "amc" and a.evidence.startswith("events feed via IR 2026-10-28: FedEx Q3 2026 Earnings Call https://investors.fedex.com/news-and-events/upcoming-events")
    assert F.release_link(a.evidence).endswith("/FedEx-Earnings-Call/default.aspx") and F.is_feed_evidence("confirmed: " + a.evidence)
    b = F.announcement_from_events(ARCH_EVENTS, T)
    assert b.day == date(2026, 10, 27) and b.timing == "amc" and "Earnings Release" in b.evidence       # the release, not the next morning's call
    assert F.announcement_from_events(EVENTS_FEED, date(2027, 3, 1)) is None                             # nothing upcoming
    assert F.event_timing("<lastBuildDate>Tue, 03 Nov 2026 07:30:00 -0500</lastBuildDate>", date(2026, 11, 3)) == "bmo"
    assert F.event_timing("<lastBuildDate>Tue, 03 Nov 2026 07:30:00 -0500</lastBuildDate>", date(2026, 11, 4)) == "unknown"


def test_a_morning_call_the_day_after_a_candidate_confirms_the_release_day_and_sales_events_are_not_earnings():
    fe = """<rss><channel><lastBuildDate>Wed, 28 Oct 2026 09:00:00 -0400</lastBuildDate><item><title>10/28/2026 : FirstEnergy Corp. - 3Q26 Earnings Call</title><link>https://investors.firstenergycorp.com/x</link></item></channel></rss>"""
    a = F.announcement_from_events(fe, T, [date(2026, 10, 27)])
    assert a.day == date(2026, 10, 27) and a.timing == "amc" and "(the morning call follows the 2026-10-27 release)" in a.evidence
    b = F.announcement_from_events(fe, T, [date(2026, 10, 28)])
    assert b.day == date(2026, 10, 28) and b.timing == "bmo"                                           # the candidate agrees: the call's own morning
    assert F.announcement_from_events(fe, T).day == date(2026, 10, 28)                                 # no candidates known: the call's day stands
    cost = """<rss><channel><lastBuildDate>Wed, 07 Oct 2026 13:15:00 -0400</lastBuildDate><item><title>10/7/2026 : September Sales Results</title></item>
    <item><title>12/10/2026 : Q1 2027 Earnings Results</title><link>https://investor.costco.com/x</link></item><item><title>12/10/2026 : Q1 2027 Earnings Call</title></item></channel></rss>"""
    c = F.announcement_from_events(cost, T, [date(2026, 12, 10)])
    assert c.day == date(2026, 12, 10) and "Q1 2027 Earnings Results" in c.evidence                   # monthly sales are not a report; the results event wins the day
