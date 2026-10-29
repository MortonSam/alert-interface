"""The opted-in emails, once a day at services/emails.SEND_HOUR New York (Sam, 2026-10-29). Sends nothing unless ACCOUNTS_ENABLED,
EMAILS_ENABLED and POSTMARK_SERVER_TOKEN are all set; a person gets at most one email a day (email_sends), and an email that breaks
the rules (services/emails.email_problems) is not sent and goes to the digest.

    python -m app.scripts.send_emails                 # dry run: who would get what, nothing sent
    python -m app.scripts.send_emails --send
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import date

from sqlalchemy import text

from app.config import settings
from app.database import ScriptSessionLocal


def unsubscribe_url(user_id: str, kind: str) -> str:
    from app.services.accounts import unsubscribe_sig
    return f"{settings.site_url}/api/v1/account/unsubscribe?u={user_id}&k={kind}&s={unsubscribe_sig(settings.account_secret, user_id, kind)}"


async def run(argv: list[str]) -> int:
    from app.services import emails as E, mailer
    from app.services.ai_spend import spend_day
    send = "--send" in argv
    today = date.fromisoformat(spend_day())
    if send and not (settings.accounts_enabled and settings.emails_enabled and settings.postmark_server_token and settings.account_secret):
        print("send_emails: accounts, emails, the provider or the signing secret is not configured; nothing sent", flush=True)
        return 0
    sent = skipped = held = 0
    async with ScriptSessionLocal() as db:
        people = (await db.execute(text("""SELECT u.id, u.email_lower, array_agg(p.kind) AS kinds FROM users u JOIN email_prefs p ON p.user_id = u.id AND p.enabled
            WHERE u.id LIKE 'acct\\_%' AND NOT EXISTS (SELECT 1 FROM email_sends s WHERE s.user_id = u.id AND s.day = :d) GROUP BY u.id, u.email_lower"""), {"d": today})).all()
        for p in people:
            sections = await E.sections_for(db, p.id, set(p.kinds), today, settings.site_url)
            em = E.merge(sections, site=settings.site_url, unsubscribe={k: unsubscribe_url(p.id, k) for k in [*p.kinds, E.ALL]},
                         settings_url=f"{settings.site_url}/account", mailing_address=settings.mailing_address)
            if em is None:
                skipped += 1
                continue
            bad = E.email_problems(em)
            if bad:
                held += 1
                from app.services import user_errors
                await user_errors.record("email", RuntimeError("; ".join(bad)[:400]), p.id)
                continue
            print(f"  {p.id}: {em.subject} ({', '.join(em.kinds)})", flush=True)
            if not send:
                continue
            pid = await mailer.send(mailer.Message(to=p.email_lower, subject=em.subject, html=em.html, text=em.text, stream=mailer.STREAM_UPDATES,
                                                   unsubscribe_url=unsubscribe_url(p.id, em.kinds[0] if len(em.kinds) == 1 else E.ALL)))
            await db.execute(text("""INSERT INTO email_sends (user_id, day, kinds, items, provider_id) VALUES (:u, :d, :k, CAST(:i AS jsonb), :p)
                ON CONFLICT DO NOTHING"""), {"u": p.id, "d": today, "k": em.kinds, "i": json.dumps(em.items), "p": pid})
            await db.commit()
            sent += 1
    print(f"send_emails: {sent} sent, {skipped} with nothing to say, {held} held for the digest ({'send' if send else 'dry run'})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
