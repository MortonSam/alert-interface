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
    return bool(note) and "press release via IR feed" in note


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
