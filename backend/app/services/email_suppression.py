"""Addresses never sent to again (Sam, 2026-11-02): a hard bounce, a spam complaint or a manual suppression, as Postmark reports it
through its webhook, or an "inactive recipient" refusal (Postmark's error 406) when a send is tried. A suppressed address gets no
email of any kind, its email settings are all turned off, and the row stays when the account is deleted, so a returning address is
not mailed into a complaint again. A reactivation Postmark reports (SuppressSending false) lifts it.

Postmark's webhook (Servers > Default > Webhooks) posts to /api/v1/account/postmark-webhook with HTTP Basic credentials in its URL
(user "postmark", password POSTMARK_WEBHOOK_SECRET). Three record types count: Bounce (only the types in HARD_BOUNCES; a soft bounce
is retried by Postmark and suppresses nothing), SpamComplaint, and SubscriptionChange (Postmark's own suppression list changing).
"""
from __future__ import annotations

import hmac

from sqlalchemy import text

HARD_BOUNCES = frozenset({"HardBounce", "BadEmailAddress", "ManuallyDeactivated", "SpamNotification", "Blocked", "DMARCPolicy"})
INACTIVE_RECIPIENT = 406                    # Postmark's ErrorCode for a send to an address on its suppression list
WEBHOOK_USER = "postmark"
REASONS = {"HardBounce": "hard_bounce", "SpamComplaint": "spam_complaint", "ManualSuppression": "manual"}


class InactiveRecipient(RuntimeError):
    """Postmark refused the send: the address is on its suppression list."""


def from_webhook(payload: dict) -> tuple[str, str | None, str] | None:
    """Pure: (email, reason or None to lift the suppression, detail) for a record that changes who may be mailed; None otherwise."""
    kind = payload.get("RecordType")
    if kind == "Bounce":
        email = payload.get("Email")
        if not email or payload.get("Type") not in HARD_BOUNCES:
            return None
        return email.lower(), "hard_bounce", f"{payload.get('Type')}: {str(payload.get('Description') or '')[:200]}"
    if kind == "SpamComplaint":
        email = payload.get("Email")
        return (email.lower(), "spam_complaint", "spam complaint") if email else None
    if kind == "SubscriptionChange":
        email = payload.get("Recipient")
        if not email:
            return None
        if payload.get("SuppressSending"):
            reason = payload.get("SuppressionReason") or ""
            return email.lower(), REASONS.get(reason, "manual"), f"Postmark suppression: {reason}"
        return email.lower(), None, "Postmark reactivated the address"
    return None


def webhook_auth_ok(secret: str, user: str | None, password: str | None) -> bool:
    """Pure: the webhook's Basic credentials match; nothing passes while no secret is set."""
    return bool(secret) and user == WEBHOOK_USER and hmac.compare_digest((password or "").encode(), secret.encode())


async def is_suppressed(db, email: str) -> bool:
    return bool(await db.scalar(text("SELECT 1 FROM email_suppressions WHERE email_lower = :e"), {"e": email.lower()}))


async def suppress(db, email: str, reason: str, source: str, detail: str | None = None) -> None:
    """Record the address and turn off every email its account had on; committed."""
    e = email.lower()
    await db.execute(text("""INSERT INTO email_suppressions (email_lower, reason, source, detail) VALUES (:e, :r, :s, :d)
        ON CONFLICT (email_lower) DO UPDATE SET reason = EXCLUDED.reason, source = EXCLUDED.source, detail = EXCLUDED.detail, at = now()"""),
                     {"e": e, "r": reason, "s": source, "d": detail})
    await db.execute(text("""UPDATE email_prefs SET enabled = false, updated_at = now()
        WHERE user_id IN (SELECT id FROM users WHERE email_lower = :e) AND enabled"""), {"e": e})
    await db.commit()


async def lift(db, email: str) -> None:
    """Postmark reactivated the address: it may be mailed again (its settings stay off until the person turns them on)."""
    await db.execute(text("DELETE FROM email_suppressions WHERE email_lower = :e"), {"e": email.lower()})
    await db.commit()
