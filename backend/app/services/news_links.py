"""Discover's links never depend on a vendor redirect: when a story is stored, its Finnhub link (finnhub.io/api/news?id=...) is
followed to the article and the article URL is stored with where it landed (news_stories.article_url, link_state).

link_state is
  - "ok":        the article page loaded;
  - "unchecked": a bot check stood in front of the page (Barchart's AWS WAF), so its content could not be read; the article
                 URL is known and the page opens in a browser;
  - "paywall":   a premium upgrade or subscription page (Yahoo's "Upgrade to read" MT Newswires pieces, a hard-paywall site);
  - "login":     the link lands on a sign-in page;
  - "broken":    no article (an error status or no response).
Only "ok" and "unchecked" links are ever shown; a story whose link is anything else, or not resolved yet, is never displayed, and
its row uses its next eligible story or none.
"""
from __future__ import annotations

import asyncio
import re
from urllib.parse import urlparse

DISPLAYABLE = ("ok", "unchecked")
TIMEOUT_SECONDS = 15.0
MAX_BODY_BYTES = 900_000
CONCURRENCY = 4                  # Finnhub's redirect fails under more parallel requests than this
CHALLENGE_MAX_TEXT = 4000        # a bot-check page has almost no visible text
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"

PAYWALL_HOSTS = ("wsj.com", "barrons.com", "ft.com", "bloomberg.com", "economist.com", "theinformation.com",
                 "seekingalpha.com")      # Seeking Alpha refuses scripts and asks visitors to sign in for most full articles
# matched against the page's visible text only (scripts and styles removed: Yahoo's stylesheet names a premium-paywall class on
# every article page)
PAYWALL_MARKERS = re.compile(
    r"upgrade to read|subscribe to (?:continue|read)|subscription (?:is )?required|this (?:article|story) is (?:for|available to) "
    r"subscribers|subscriber[- ]only|to continue reading,? (?:please )?(?:subscribe|sign in|log in)|create a free account to (?:continue|read)|"
    r"sign in to (?:read|continue)|log in to (?:read|continue)", re.I)
LOGIN_PATH = re.compile(r"/(?:login|log-in|signin|sign-in|sso|auth|account/login|subscribe|paywall)\b", re.I)
BOT_CHECK = re.compile(r"awsWafCookieDomainList|gokuProps|cf-chl|challenge-platform|Just a moment\.\.\.|captcha|access denied", re.I)
BLOCKING_STATUS = (202, 401, 403, 429, 503)          # a site that refused a script at the article's own URL: it opens in a browser


def visible_text(html: str) -> str:
    """Pure: the page's text without scripts, styles and tags."""
    t = re.sub(r"<(script|style|noscript|svg)\b[^>]*>.*?</\1>", " ", html or "", flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))


def is_vendor_redirect(url: str) -> bool:
    return urlparse(url).netloc.lower().endswith("finnhub.io")


def classify(final_url: str | None, status: int | None, body: str) -> str:
    """Pure: where a link landed, from its final URL, status and the start of its page."""
    if not final_url or status is None:
        return "broken"
    parsed = urlparse(final_url)
    host = parsed.netloc.lower()
    if is_vendor_redirect(final_url):
        return "broken"                                   # the redirect did not leave the vendor
    if LOGIN_PATH.search(parsed.path) or host.startswith(("login.", "signin.", "auth.", "sso.")):
        return "login"
    if any(host == h or host.endswith("." + h) for h in PAYWALL_HOSTS):
        return "paywall"
    text_ = visible_text(body)
    if status in BLOCKING_STATUS or (BOT_CHECK.search(body or "") and len(text_) < CHALLENGE_MAX_TEXT):
        return "unchecked"
    if status >= 400:
        return "broken"
    if PAYWALL_MARKERS.search(text_):
        return "paywall"
    return "ok"


async def resolve(client, url: str) -> tuple[str | None, str]:
    """(article URL, link_state) for one stored link, tried twice. A link that is not a vendor redirect is checked where it points."""
    first = await _resolve_once(client, url)
    if first[1] != "broken":
        return first
    await asyncio.sleep(2)
    return await _resolve_once(client, url)


async def _resolve_once(client, url: str) -> tuple[str | None, str]:
    try:
        async with client.stream("GET", url, follow_redirects=True, timeout=TIMEOUT_SECONDS) as resp:
            chunks, size = [], 0
            async for chunk in resp.aiter_bytes():
                chunks.append(chunk)
                size += len(chunk)
                if size >= MAX_BODY_BYTES:
                    break
            body = b"".join(chunks).decode("utf-8", errors="ignore")
            final = str(resp.url)
            return (final if not is_vendor_redirect(final) else None), classify(final, resp.status_code, body)
    except Exception:
        return None, "broken"


async def resolve_many(urls: list[str]) -> dict[str, tuple[str | None, str]]:
    import httpx
    out: dict[str, tuple[str | None, str]] = {}
    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}) as client:
        async def one(u: str) -> None:
            async with sem:
                out[u] = await resolve(client, u)
        await asyncio.gather(*(one(u) for u in urls))
    return out
