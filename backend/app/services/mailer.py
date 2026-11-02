"""Sending email (Postmark's HTTP API; recommended in backend/ops/reports/accounts_2026-10-29/report.md). Nothing is sent without
POSTMARK_SERVER_TOKEN, and nothing but a sign-in link is sent without EMAILS_ENABLED. Every email to a person carries List-Unsubscribe
and List-Unsubscribe-Post headers (one-click unsubscribe, RFC 8058) besides the link in its footer.

Two Postmark message streams (Sam, 2026-11-02): the transactional stream carries the sign-in link and the per-stock alerts a person
asked for (date confirmed, earnings eve, morning after), each sent because of one event on one stock; the broadcast stream carries
the Sunday earnings-week email, the same list to everyone who turned it on. A day's merged email that holds the Sunday email goes as
broadcast. The stream ids are Postmark's (POSTMARK_TRANSACTIONAL_STREAM, default "outbound", the id Postmark gives every server's
transactional stream; POSTMARK_BROADCAST_STREAM, default "broadcast", the id Postmark suggests for the broadcast stream Sam creates).
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import settings

POSTMARK_URL = "https://api.postmarkapp.com/email"
TRANSACTIONAL = "transactional"     # the sign-in link and the per-stock alerts
BROADCAST = "broadcast"             # the Sunday earnings-week email
BROADCAST_KINDS = frozenset({"earnings_week"})
SECONDS = 20


def stream_for(kinds: list[str] | tuple[str, ...]) -> str:
    """Pure: the stream an opted-in email goes on: broadcast when it holds a broadcast kind, else transactional."""
    return BROADCAST if any(k in BROADCAST_KINDS for k in kinds) else TRANSACTIONAL


def stream_id(stream: str) -> str:
    """Postmark's id for the stream, from the settings."""
    return settings.postmark_broadcast_stream if stream == BROADCAST else settings.postmark_transactional_stream


@dataclass
class Message:
    to: str
    subject: str
    html: str
    text: str
    stream: str = TRANSACTIONAL
    unsubscribe_url: str | None = None
    sign_in: bool = False               # the sign-in link: the one email sent while EMAILS_ENABLED is off


def payload(m: Message) -> dict:
    """Pure: the Postmark request body."""
    body = {"From": settings.email_from, "To": m.to, "Subject": m.subject, "HtmlBody": m.html, "TextBody": m.text, "MessageStream": stream_id(m.stream)}
    if m.unsubscribe_url:
        body["Headers"] = [{"Name": "List-Unsubscribe", "Value": f"<{m.unsubscribe_url}>"},
                           {"Name": "List-Unsubscribe-Post", "Value": "List-Unsubscribe=One-Click"}]
    return body


async def send(m: Message) -> str | None:
    """The provider's message id, or None when sending is not configured (the caller records nothing as sent)."""
    if not settings.postmark_server_token:
        return None
    if not m.sign_in and not settings.emails_enabled:
        return None
    async with httpx.AsyncClient(timeout=SECONDS) as c:
        r = await c.post(POSTMARK_URL, json=payload(m), headers={"X-Postmark-Server-Token": settings.postmark_server_token, "Accept": "application/json"})
        r.raise_for_status()
        return r.json().get("MessageID")
