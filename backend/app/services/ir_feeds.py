"""Investor-relations press-release feeds (ir_feeds, found by scripts/discover_ir_feeds) as a company-announcement source.

Phase 2 of the feed work: for a ticker whose next candidate report date is near, the nightly calendar refresh reads the
company's press-release feed, takes the items whose title says the company will announce its results, follows each item's
link to the release page (the Q4-hosted feeds carry titles only) and runs the announcement detector
(report_announcements.find_announced_date) over the release. A detected date counts as the company's own confirmation
only when the item's title names the issuer (report_announcements.names_issuer): a subsidiary's or partner's release
confirms nothing. Only feeds classified press_releases are read; blogs and placeholder feeds are left alone.

Every host's robots.txt is read first, and a URL it disallows for our agent or for everyone is never requested.
"""
from __future__ import annotations

import html as html_
import re
from datetime import date
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import httpx

from app.services.report_announcements import Announcement, find_announced_date, names_issuer

UA = "alert-interface IR feed reader (sammyjmorton@gmail.com)"
TIMEOUT = 10.0
PRESS_RELEASES = "press_releases"          # ir_feeds.classification values: press_releases | blog | placeholder | unreviewed
MAX_CANDIDATES = 4                         # announcement-looking items followed per feed per night
_ITEM = re.compile(r"<(item|entry)\b.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<(title|link|description|summary|content:encoded|content|pubDate|published|updated)\b[^>]*>(.*?)</\1>", re.S | re.I)
_HREF = re.compile(r'<link\b[^>]*href="([^"]+)"', re.I)
_CDATA = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.S)
_STRIP = re.compile(r"<(script|style)\b.*?</\1>|<[^>]+>", re.S | re.I)
# a title that says the company will report, release or announce results, or has set the date or call for them
ANNOUNCE_TITLE = re.compile(r"\b(?:to (?:report|release|announce|host|hold)|announces?|schedules?|sets?|confirms?|invites?|details)\b.{0,80}"
                            r"\b(?:results|earnings|conference call|webcast)\b|\b(?:earnings|results) (?:release|call|conference call|webcast) (?:date|details)\b", re.I)
# a results release itself, or a dividend notice, is not an announcement of a results date
NOT_ANNOUNCEMENT = re.compile(r"(?<!to )\breports\b|\bdividend\b|\bdeclares?\b|\bfinancial results for\b|\bannounces? (?:first|second|third|fourth)[- ]quarter (?:(?:fiscal )?\d{4} )?(?:financial )?results\b(?! (?:date|call|webcast|conference))", re.I)

_ROBOTS: dict[str, robotparser.RobotFileParser] = {}

# Q4-platform events feed: /rss/event.aspx (every Q4 host probed returns 404 for /rss/events.xml). Items read "M/D/YYYY : <title>" and the
# channel's lastBuildDate is the first event's start time; the page link is the receipt. A scheduled earnings call, results release or
# results webcast on the company's own events feed is the company's confirmation of its report date.
EVENTS_FEED_PATH = "/rss/event.aspx"
PRESS_FEED_PATH = "/rss/pressrelease.aspx"
_EVENT_TITLE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*:\s*(.+?)\s*$")
EARNINGS_EVENT = re.compile(r"\b(?:earnings|financial results|results)\b", re.I)
NOT_EARNINGS_EVENT = re.compile(r"annual meeting|investor day|analyst day|shareholder|conference(?!\s+call)|presentation|dividend|roadshow|summit|sales results|monthly|same.store", re.I)
_CALL_ONLY = re.compile(r"\b(?:call|webcast)\b", re.I)
_RELEASE_WORD = re.compile(r"\b(?:release|announce|announces|report|reports|results)\b", re.I)
_BUILD_DATE = re.compile(r"<lastBuildDate>([^<]+)</lastBuildDate>", re.I)
_TIME = re.compile(r"\b(\d{1,2}):(\d{2}):\d{2}\s*([+-]\d{4})?")


def events_feed_url(press_feed_url: str | None) -> str | None:
    """Pure: the events feed beside a Q4 press-release feed; None for any other platform."""
    if not press_feed_url or PRESS_FEED_PATH not in press_feed_url:
        return None
    return press_feed_url.split("/rss/", 1)[0] + EVENTS_FEED_PATH


def earnings_events(items: list[dict], today: date) -> list[dict]:
    """Pure: [{day, title, link}] for the feed's upcoming earnings events (a call, release or results webcast), feed order."""
    out = []
    for it in items:
        m = _EVENT_TITLE.match(it.get("title") or "")
        if not m:
            continue
        try:
            day = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            continue
        title = m.group(4)
        if day >= today and EARNINGS_EVENT.search(title) and not NOT_EARNINGS_EVENT.search(title):
            out.append({"day": day, "title": title, "link": it.get("link") or ""})
    return out


def event_timing(body: str, day: date) -> str:
    """Pure: amc, bmo or unknown from the channel's lastBuildDate when it falls on `day` (Q4 sets it to the first event's start time)."""
    m = _BUILD_DATE.search(body or "")
    if not m or f"{day.day:02d} " not in m.group(1) and f" {day.day} " not in m.group(1):
        return "unknown"
    t = _TIME.search(m.group(1))
    if not t:
        return "unknown"
    hour = int(t.group(1))
    return "amc" if hour >= 16 else "bmo" if hour < 12 else "unknown"


def announcement_from_events(body: str, today: date, candidates: list[date] | None = None) -> Announcement | None:
    """Pure: the earliest upcoming earnings event as the company's confirmation. When a results release and its call fall on different
    days, the earlier (the release) is the report date. A call alone in the morning is the standard follow-up to a release the evening
    before: when a calendar candidate sits on the previous day, the report is that day, after the close (FirstEnergy's 3Q26 call at
    09:00 on Oct 28 follows its Oct 27 release; Assurant's Nov 4 08:00 call follows Nov 3); otherwise the call's own day stands."""
    events = earnings_events(parse_items(body or "", ""), today)
    if not events:
        return None
    first = min(events, key=lambda e: e["day"])
    day, timing = first["day"], event_timing(body, first["day"])
    link = f" {first['link']}" if first["link"] else ""
    call_only = bool(_CALL_ONLY.search(first["title"])) and not _RELEASE_WORD.search(_CALL_ONLY.sub("", first["title"]).replace("Earnings", ""))
    if call_only and timing == "bmo" and any((day - c).days in (1, 2, 3) and c.weekday() < 5 for c in candidates or []):
        prev = max(c for c in candidates if (day - c).days in (1, 2, 3))
        return Announcement(prev, "amc", f"events feed via IR {day.isoformat()}: {first['title'][:80]} (the morning call follows the {prev.isoformat()} release){link}")
    return Announcement(day, timing, f"events feed via IR {day.isoformat()}: {first['title'][:80]}{link}")


async def from_events_feed(client: httpx.AsyncClient, press_feed_url: str, today: date, candidates: list[date] | None = None) -> tuple[Announcement | None, str]:
    """(announcement, what was read) from the Q4 events feed beside a press-release feed; (None, why) for other platforms."""
    url = events_feed_url(press_feed_url)
    if url is None:
        return None, "no events feed (not a Q4 host)"
    body = await fetch_allowed(client, url)
    if body is None:
        return None, "events feed not readable (robots, error or non-200)"
    hit = announcement_from_events(body, today, candidates)
    return hit, f"events feed {len(parse_items(body, url))} items, {len(earnings_events(parse_items(body, url), today))} upcoming earnings event(s)"


def clean(fragment: str) -> str:
    """Pure: text of an XML/HTML fragment, CDATA unwrapped, tags and scripts removed, entities decoded, whitespace folded."""
    return re.sub(r"\s+", " ", html_.unescape(_STRIP.sub(" ", _CDATA.sub(r"\1", fragment)))).strip()


def parse_items(body: str, feed_url: str = "") -> list[dict]:
    """Pure: the feed's items in feed order as {title, link, text, published}; `text` is the title plus any description."""
    out = []
    for m in _ITEM.finditer(body):
        f: dict[str, str] = {}
        for t in _TAG.finditer(m.group(0)):
            f.setdefault(t.group(1).lower(), clean(t.group(2)))
        href = _HREF.search(m.group(0))
        link = f.get("link") or (href.group(1) if href else "")
        desc = f.get("description") or f.get("summary") or f.get("content:encoded") or f.get("content") or ""
        out.append({"title": f.get("title", ""), "link": urljoin(feed_url, link) if link else "", "text": (f.get("title", "") + ". " + desc).strip(". ").strip(),
                    "published": f.get("pubdate") or f.get("published") or f.get("updated") or ""})
    return out


def looks_like_announcement(title: str) -> bool:
    """Pure: the title announces a results date or call (not the results themselves, not a dividend)."""
    return bool(ANNOUNCE_TITLE.search(title)) and not NOT_ANNOUNCEMENT.search(title)


def names_company(title: str, issuer: str | None, symbol: str | None) -> bool:
    """Pure: on the company's own feed, a title names the issuer when it names the stored company name (names_issuer) or
    carries the ticker symbol as a word ("ADP to Announce First Quarter Fiscal 2027 Financial Results")."""
    if issuer is None and symbol is None:
        return True
    if issuer is not None and names_issuer(title, issuer):
        return True
    return bool(symbol) and re.search(rf"(?<![A-Za-z]){re.escape(symbol)}(?![A-Za-z])", title) is not None


def candidates(items: list[dict], issuer: str | None, symbol: str | None = None) -> list[dict]:
    """Pure: the items worth following: announcement-looking titles that name the issuer, feed order, at most MAX_CANDIDATES."""
    out = [it for it in items if looks_like_announcement(it["title"]) and names_company(it["title"], issuer, symbol)]
    return out[:MAX_CANDIDATES]


def evidence_for(item: dict) -> str:
    """The note a confirmation from this item carries: source, item date, title, then the release link for spot-checks."""
    pub = item.get("published") or "?"
    return f"press release via IR feed {pub[:25]}: {item['title'][:80]}" + (f" {item['link']}" if item.get("link") else "")


def announcement_from_items(items: list[dict], pages: dict[str, str], issuer: str | None, today: date, symbol: str | None = None) -> Announcement | None:
    """Pure: the first announced results date among the candidate items, read from the item text first and then from the
    release page text (`pages` maps link to text), with the item as evidence."""
    for it in candidates(items, issuer, symbol):
        hit = find_announced_date(it["text"], today, evidence_for(it))
        if hit is None and it.get("link") and pages.get(it["link"]):
            hit = find_announced_date(pages[it["link"]], today, evidence_for(it))
        if hit:
            return hit
    return None


def release_link(evidence: str) -> str | None:
    """Pure: the release link an IR-feed evidence string ends with, for the digest."""
    m = re.search(r"\s(https?://\S+)$", evidence or "")
    return m.group(1) if m else None


def is_feed_evidence(note: str | None) -> bool:
    return bool(note) and ("press release via IR feed" in note or "events feed via IR" in note)


# ── fetching, robots first ───────────────────────────────────────────────────

async def robots_for(client: httpx.AsyncClient, base: str) -> robotparser.RobotFileParser:
    """The parsed robots.txt of a scheme://host, fetched once per process; an unreachable or missing file allows everything."""
    if base not in _ROBOTS:
        rp = robotparser.RobotFileParser()
        try:
            r = await client.get(base + "/robots.txt", timeout=TIMEOUT, follow_redirects=True)
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except Exception:
            rp.parse([])
        _ROBOTS[base] = rp
    return _ROBOTS[base]


def allowed(rp: robotparser.RobotFileParser, url: str, agent: str = UA) -> bool:
    """Pure: a URL is requested only when robots.txt allows it both for our agent and for everyone."""
    return rp.can_fetch(agent, url) and rp.can_fetch("*", url)


async def fetch_allowed(client: httpx.AsyncClient, url: str) -> str | None:
    """The body of a URL robots.txt allows, else None (also None on any error or non-200)."""
    u = urlparse(url)
    if not u.scheme or not u.netloc or not allowed(await robots_for(client, f"{u.scheme}://{u.netloc}"), url):
        return None
    try:
        r = await client.get(url, timeout=TIMEOUT, follow_redirects=True)
    except Exception:
        return None
    return r.text if r.status_code == 200 else None


async def from_feed(client: httpx.AsyncClient, feed_url: str, issuer: str | None, today: date, symbol: str | None = None) -> tuple[Announcement | None, str]:
    """(announcement, what was read) for one feed: the feed body, then the release page of each candidate item until one
    names a results date. Nothing is cached between nights; a feed is at most a few kilobytes."""
    body = await fetch_allowed(client, feed_url)
    if body is None:
        return None, "feed not readable (robots, error or non-200)"
    items = parse_items(body, feed_url)
    cands = candidates(items, issuer, symbol)
    pages: dict[str, str] = {}
    hit = announcement_from_items(items, pages, issuer, today, symbol)
    if hit is None:
        for it in cands:
            if it.get("link"):
                page = await fetch_allowed(client, it["link"])
                if page:
                    pages[it["link"]] = clean(page)
        hit = announcement_from_items(items, pages, issuer, today, symbol)
    said = f"IR feed {len(items)} items, {len(cands)} announcement-looking" + (f", {len(pages)} release page(s) read" if pages else "")
    return hit, said
