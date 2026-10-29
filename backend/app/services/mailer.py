"""Sending email (Postmark's HTTP API; recommended in backend/ops/reports/accounts_2026-10-29/report.md). Nothing is sent without
POSTMARK_SERVER_TOKEN, and nothing but a sign-in link is sent without EMAILS_ENABLED. Every email to a person carries List-Unsubscribe
and List-Unsubscribe-Post headers (one-click unsubscribe, RFC 8058) besides the link in its footer.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import settings

POSTMARK_URL = "https://api.postmarkapp.com/email"
STREAM_SIGN_IN = "outbound"          # Postmark's transactional stream: the sign-in link
STREAM_UPDATES = "broadcast"         # the opted-in emails, on their own stream so their reputation never touches sign-in mail
SECONDS = 20


@dataclass
class Message:
    to: str
    subject: str
    html: str
    text: str
    stream: str = STREAM_SIGN_IN
    unsubscribe_url: str | None = None


def payload(m: Message) -> dict:
    """Pure: the Postmark request body."""
    body = {"From": settings.email_from, "To": m.to, "Subject": m.subject, "HtmlBody": m.html, "TextBody": m.text, "MessageStream": m.stream}
    if m.unsubscribe_url:
        body["Headers"] = [{"Name": "List-Unsubscribe", "Value": f"<{m.unsubscribe_url}>"},
                           {"Name": "List-Unsubscribe-Post", "Value": "List-Unsubscribe=One-Click"}]
    return body


async def send(m: Message) -> str | None:
    """The provider's message id, or None when sending is not configured (the caller records nothing as sent)."""
    if not settings.postmark_server_token:
        return None
    if m.stream != STREAM_SIGN_IN and not settings.emails_enabled:
        return None
    async with httpx.AsyncClient(timeout=SECONDS) as c:
        r = await c.post(POSTMARK_URL, json=payload(m), headers={"X-Postmark-Server-Token": settings.postmark_server_token, "Accept": "application/json"})
        r.raise_for_status()
        return r.json().get("MessageID")
