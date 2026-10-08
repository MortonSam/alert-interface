"""Discover news: "Today's biggest movers" and "In the news", from stored Finnhub headlines (news_stories, the last 24 hours) and the
quote snapshot the same step stores (quote_snapshots). Headlines only: no article text, no summaries. A headline beside a move is
labelled "In the news:" and never "because": being next to a move does not make it the cause.

Fail closed: when the newest stored story is more than FRESH_HOURS old, or the news step's last run failed, neither section shows.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")

FRESH_HOURS = 24            # stories are kept for this long, and the sections hide when the newest is older
MOVERS_EACH_SIDE = 5
IN_THE_NEWS_LIMIT = 10
STORIES_PER_TICKER = 2      # "In the news" ranks by the related stock's move; at most this many stories per stock, so one mover cannot fill it
STEP_LABEL = "Discover news (Finnhub)"
ROUNDUP_TICKERS = 3          # a story tagged to more companies than this is a roundup ("these Dow stocks are moving"), not news about one


_SUFFIX = re.compile(r"[,.]?\s+(?:inc\.?|incorporated|corp\.?|corporation|co\.?|company|holdings?|group|plc|ltd\.?|limited|n\.?v\.?|s\.?a\.?|"
                     r"common stock|class [a-c]|& co\.?|the)$", re.I)
_GENERIC_FIRST = {"american", "general", "first", "united", "international", "national", "the", "global", "bank", "public", "southern",
                  "eli", "texas", "western", "eastern", "northern", "royal", "digital", "realty", "energy", "health", "capital"}
_WORD_TICKERS = {"A", "ALL", "ARE", "BE", "BALL", "CAT", "CF", "DAY", "DD", "EL", "ES", "FAST", "GE", "GL", "HAS", "IT", "KEY", "KO", "LOW",
                 "MA", "MO", "NOW", "ON", "O", "PEG", "PH", "PM", "PSA", "SO", "T", "TT", "V", "WELL", "AI", "ICE", "J", "K", "L", "D", "C", "F"}


def name_forms(symbol: str, name: str | None) -> list[str]:
    """Pure: the words that name a company in a headline: its name without corporate suffixes ("Home Depot"), its first word when
    distinctive ("Micron", "Exxon"), and its ticker when the ticker is not an everyday word or a single letter."""
    forms: list[str] = []
    n = (name or "").strip()
    while n and _SUFFIX.search(n):
        n = _SUFFIX.sub("", n).strip()
    n = re.sub(r"^the\s+", "", n, flags=re.I).strip(" ,.")
    if n:
        forms.append(n)
        first = n.split()[0].strip(",.")
        if len(first) >= 4 and first.lower() not in _GENERIC_FIRST and first != n:
            forms.append(first)
    if len(symbol) >= 2 and symbol not in _WORD_TICKERS:
        forms.append(symbol)
    return forms


def names_company(headline: str, symbol: str, name: str | None) -> bool:
    """Pure: the headline names the company (its name, distinctive first word, or ticker as a whole word)."""
    for f in name_forms(symbol, name):
        flags = 0 if f == symbol else re.I
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(f)}(?:'s|’s)?(?![A-Za-z0-9])", headline, flags):
            return True
    return False


# Established news organisations, preferred over everything else for a mover's headline (then newest). Finnhub labels most stories
# "Yahoo" behind its own redirect link, which cannot tell Yahoo Finance's own reporting from the syndicated pieces it carries, so
# "Yahoo" is in the second tier with the rest.
ESTABLISHED_SOURCES = {"reuters", "bloomberg", "dow jones", "the wall street journal", "wall street journal", "wsj", "marketwatch",
                       "barron's", "barrons", "cnbc", "associated press", "ap", "financial times", "ft"}
_TEMPLATE = re.compile(r"buy,?\s+sell,?\s+or\s+hold|should\s+you\s+buy|stocks?\s+to\s+watch|is\s+it\s+time\s+to|\?\s*[\"'’”]?\s*$", re.I)
_UPCOMING = re.compile(r"earnings\s+preview|ahead\s+of\s+(?:its\s+|the\s+)?(?:q[1-4]\b|earnings|results|report)|next\s+earnings|"
                       r"(?:to|will)\s+report\s+(?:q[1-4]|earnings|results)|earnings\s+(?:are\s+)?(?:expected|on\s+deck|due)", re.I)
_QUARTER = re.compile(r"\bq[1-4]\b|\b(?:first|second|third|fourth)[- ]quarter\b|\bquarterly\b|\bearnings\b|\bresults\b|\bEPS\b", re.I)
REPORT_HEADLINE_DAYS = 14     # a headline naming an earnings quarter counts only this soon after the company's latest report


def source_tier(source: str | None) -> int:
    """Pure: 0 for an established news organisation, 1 for everything else."""
    return 0 if (source or "").strip().lower() in ESTABLISHED_SOURCES else 1


def previous_session_close(session_day) -> datetime:
    """Pure: 4:00 PM New York on the last trading day before `session_day` (the newest session in the quote snapshot)."""
    from app.services.trading_calendar import is_trading_day
    d = session_day - timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return datetime(d.year, d.month, d.day, 16, 0, tzinfo=NEW_YORK)


def headline_problem(story: dict, symbol: str, name: str | None, last_report, since: datetime) -> str | None:
    """Pure: why a story cannot stand as this company's headline, or None. In order: published before the previous session's close;
    a roundup; does not name the company; a question or template headline; about an upcoming report; names an earnings quarter but
    was not published within REPORT_HEADLINE_DAYS after the company's latest report (so it is about another quarter)."""
    h = story["headline"]
    if story["published_at"] < since:
        return "published before the previous session's close"
    if len(story["related"]) > ROUNDUP_TICKERS:
        return "a roundup about several companies"
    if not names_company(h, symbol, name):
        return "does not name the company"
    if _TEMPLATE.search(h):
        return "a question or template headline"
    if _UPCOMING.search(h):
        return "about an upcoming report, not the latest one"
    if _QUARTER.search(h):
        day = story["published_at"].astimezone(NEW_YORK).date()
        if last_report is None or not 0 <= (day - last_report).days <= REPORT_HEADLINE_DAYS:
            when = f"latest report {last_report.isoformat()}" if last_report else "no stored report"
            return f"names an earnings quarter but is not from the {REPORT_HEADLINE_DAYS} days after the company's latest report ({when})"
    return None


def story_time(item: dict) -> datetime | None:
    ts = item.get("datetime")
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc) if ts else None
    except (TypeError, ValueError, OSError):
        return None


def dedupe(raw: list[tuple[str, dict]], now: datetime, universe: set[str]) -> dict[str, dict]:
    """Pure: {url: story} from (category, Finnhub item) pairs: one story per URL (and per headline from one source), related
    tickers merged and kept to the S&P 500, published within FRESH_HOURS and not in the future."""
    out: dict[str, dict] = {}
    seen_headline: dict[tuple[str, str], str] = {}
    cutoff = now - timedelta(hours=FRESH_HOURS)
    for category, item in raw:
        url = (item.get("url") or "").strip()
        headline = " ".join((item.get("headline") or "").split())
        published = story_time(item)
        if not url or not headline or published is None or published < cutoff or published > now + timedelta(minutes=10):
            continue
        related = {s.strip().upper().replace(".", "-") for s in (item.get("related") or "").split(",") if s.strip()} & universe
        key = (headline.lower(), (item.get("source") or "").lower())
        url = seen_headline.get(key, url)
        if url in out:
            out[url]["related"] = sorted(set(out[url]["related"]) | related)
            if category == "company":
                out[url]["category"] = "company"
            continue
        seen_headline[key] = url
        out[url] = {"url": url, "headline": headline, "source": (item.get("source") or "").strip() or None,
                    "published_at": published, "related": sorted(related), "category": category}
    return out


@dataclass
class Visibility:
    visible: bool
    reason: str | None


def visibility(newest_story: datetime | None, step_exit: int | None, now: datetime, newest_quote: datetime | None = None) -> Visibility:
    """Pure: whether the sections show. Hidden when the step's last run failed, no story is stored, the newest story is older than
    FRESH_HOURS, or the quote snapshot the moves come from is older than FRESH_HOURS."""
    if step_exit not in (None, 0):
        return Visibility(False, "the news step's last run failed")
    if newest_quote is None or now - newest_quote > timedelta(hours=FRESH_HOURS):
        return Visibility(False, f"no quote snapshot from the last {FRESH_HOURS} hours")
    if newest_story is None:
        return Visibility(False, "no stories stored")
    if now - newest_story > timedelta(hours=FRESH_HOURS):
        return Visibility(False, f"the newest story is more than {FRESH_HOURS} hours old")
    return Visibility(True, None)


def session_quotes(quotes: list[dict]) -> list[dict]:
    """Pure: the quotes from the newest trading session in the snapshot (a stock whose last trade is from an earlier day is not
    today's mover), each with a percent change."""
    dated = [q for q in quotes if q.get("quote_time") is not None and q.get("change_pct") is not None and q.get("price")]
    if not dated:
        return []
    newest_day = max(q["quote_time"].astimezone(NEW_YORK).date() for q in dated)
    return [q for q in dated if q["quote_time"].astimezone(NEW_YORK).date() == newest_day]


def movers(quotes: list[dict], n: int = MOVERS_EACH_SIDE) -> tuple[list[dict], list[dict]]:
    """Pure: (the n biggest gainers, the n biggest decliners) by percent change in the newest session."""
    qs = session_quotes(quotes)
    up = sorted([q for q in qs if q["change_pct"] > 0], key=lambda q: (-q["change_pct"], q["symbol"]))[:n]
    down = sorted([q for q in qs if q["change_pct"] < 0], key=lambda q: (q["change_pct"], q["symbol"]))[:n]
    return up, down


def top_headline(stories: list[dict], symbol: str, name: str | None = None, last_report=None, since: datetime | None = None) -> dict | None:
    """Pure: the company's headline: among its stories with no headline_problem, an established source first, then the newest. Finnhub
    tags loosely (a PepsiCo story under KO), so the headline must name the company; a mover with no qualifying story shows none."""
    since = since or datetime.min.replace(tzinfo=timezone.utc)
    mine = [s for s in stories if symbol in s["related"] and headline_problem(s, symbol, name, last_report, since) is None]
    return min(mine, key=lambda s: (source_tier(s.get("source")), -s["published_at"].timestamp())) if mine else None


def in_the_news(stories: list[dict], change: dict[str, float], limit: int = IN_THE_NEWS_LIMIT,
                per_ticker: int = STORIES_PER_TICKER, names: dict[str, str | None] | None = None,
                last_reports: dict | None = None, since: datetime | None = None) -> list[dict]:
    """Pure: up to `limit` stories about S&P 500 companies, ranked by the size of the related stock's move today, then recency; at
    most `per_ticker` per stock. A story counts for a related stock only when its headline names that company, and it is shown under
    the named stock with the biggest move."""
    rows = []
    for s in stories:
        since_ = since or datetime.min.replace(tzinfo=timezone.utc)
        moved = [(abs(change[t]), t) for t in s["related"]
                 if t in change and headline_problem(s, t, (names or {}).get(t), (last_reports or {}).get(t), since_) is None]
        if not moved:
            continue
        size, sym = max(moved)
        rows.append({**s, "symbol": sym, "move": size})
    rows.sort(key=lambda r: (-r["move"], -r["published_at"].timestamp()))
    out, per = [], {}
    for r in rows:
        if per.get(r["symbol"], 0) >= per_ticker:
            continue
        per[r["symbol"]] = per.get(r["symbol"], 0) + 1
        out.append(r)
        if len(out) == limit:
            break
    return out
