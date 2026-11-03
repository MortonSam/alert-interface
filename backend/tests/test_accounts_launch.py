"""Accounts launch scope (Sam, 2026-11-02): the Sunday email off until SUNDAY_EMAIL_ENABLED, Postmark's bounces and spam complaints
never mailed again, no open or link tracking, and every link to the site tagged for its analytics."""
import base64
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.config import settings
from app.database import ScriptSessionLocal
from app.services import account_copy as K
from app.services import email_suppression as SUP
from app.services import emails as E
from app.services import mailer

pytestmark = pytest.mark.xdist_group(name="accounts")

SITE = "https://alertinterface.com"


def test_the_sunday_email_is_offered_only_with_its_flag():
    assert set(K.offered_kinds(False)) == {"date_confirmed", "earnings_eve", "morning_after"}
    assert set(K.offered_kinds(True)) == set(K.KINDS)
    assert settings.sunday_email_enabled is False


def test_postmark_tracks_nothing_and_every_site_link_carries_its_tags():
    body = mailer.payload(mailer.Message(to="a@b.c", subject="s", html="h", text="t"))
    assert body["TrackOpens"] is False and body["TrackLinks"] == "None"
    assert E.tag(f"{SITE}/tickers/NVDA", "earnings_eve") == \
        f"{SITE}/tickers/NVDA?utm_source=alertinterface_email&utm_medium=email&utm_campaign=earnings_eve"
    assert E.tag(f"{SITE}/x?a=1", "date_confirmed").startswith(f"{SITE}/x?a=1&utm_source=")
    eve = E.eve_section({"symbol": "MSFT", "name": "Microsoft", "date": date(2026, 10, 30), "timing": "amc", "read": "A read.",
                         "typical": 4.1, "n": 20}, SITE)
    em = E.merge([eve], site=SITE, unsubscribe={"earnings_eve": f"{SITE}/u/eve", E.ALL: f"{SITE}/u/all"},
                 settings_url=f"{SITE}/account", mailing_address="ADDR")
    assert f"{SITE}/tickers/MSFT?utm_source=alertinterface_email&amp;utm_medium=email&amp;utm_campaign=earnings_eve" in em.html \
        or f"{SITE}/tickers/MSFT?utm_source=alertinterface_email&utm_medium=email&utm_campaign=earnings_eve" in em.html
    assert f"{SITE}/u/eve" in em.text and "/u/eve?utm" not in em.text                 # the unsubscribe and settings links stay untagged


def test_only_hard_bounces_complaints_and_suppressions_change_who_is_mailed():
    assert SUP.from_webhook({"RecordType": "Bounce", "Type": "HardBounce", "Email": "A@B.C", "Description": "no such user"})[:2] == ("a@b.c", "hard_bounce")
    assert SUP.from_webhook({"RecordType": "Bounce", "Type": "SoftBounce", "Email": "a@b.c"}) is None       # Postmark retries a soft bounce
    assert SUP.from_webhook({"RecordType": "SpamComplaint", "Email": "a@b.c"})[:2] == ("a@b.c", "spam_complaint")
    assert SUP.from_webhook({"RecordType": "SubscriptionChange", "Recipient": "a@b.c", "SuppressSending": True,
                             "SuppressionReason": "ManualSuppression"})[:2] == ("a@b.c", "manual")
    assert SUP.from_webhook({"RecordType": "SubscriptionChange", "Recipient": "a@b.c", "SuppressSending": False})[:2] == ("a@b.c", None)
    assert SUP.from_webhook({"RecordType": "Delivery", "Recipient": "a@b.c"}) is None
    assert not SUP.webhook_auth_ok("", "postmark", "")                                   # no secret set: nothing passes
    assert SUP.webhook_auth_ok("s3", "postmark", "s3") and not SUP.webhook_auth_ok("s3", "postmark", "no")


@pytest.mark.asyncio
async def test_the_webhook_suppresses_an_address_and_its_settings_and_a_reactivation_lifts_it(monkeypatch):
    email, uid = "zz-suppress-test@example.com", "acct_zz-suppress-test"
    monkeypatch.setattr(settings, "accounts_enabled", True)
    monkeypatch.setattr(settings, "postmark_webhook_secret", "s3cret")
    good = {"Authorization": "Basic " + base64.b64encode(b"postmark:s3cret").decode()}
    bad = {"Authorization": "Basic " + base64.b64encode(b"postmark:nope").decode()}
    async with ScriptSessionLocal() as db:
        await db.execute(text("DELETE FROM email_suppressions WHERE email_lower = :e"), {"e": email})
        await db.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
        await db.execute(text("INSERT INTO users (id, email_lower) VALUES (:u, :e)"), {"u": uid, "e": email})
        await db.execute(text("INSERT INTO email_prefs (user_id, kind, enabled) VALUES (:u, 'earnings_eve', true)"), {"u": uid})
        await db.commit()
    try:
        from app.main import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            record = {"RecordType": "SpamComplaint", "Email": email.upper()}
            assert (await c.post("/api/v1/account/postmark-webhook", json=record, headers=bad)).status_code == 401
            r = await c.post("/api/v1/account/postmark-webhook", json=record, headers=good)
            assert r.status_code == 200 and r.json()["change"] == "spam_complaint"
            async with ScriptSessionLocal() as db:
                assert await SUP.is_suppressed(db, email)
                assert (await db.execute(text("SELECT enabled FROM email_prefs WHERE user_id = :u"), {"u": uid})).scalar() is False
            lifted = {"RecordType": "SubscriptionChange", "Recipient": email, "SuppressSending": False}
            assert (await c.post("/api/v1/account/postmark-webhook", json=lifted, headers=good)).json()["change"] == "lifted"
            async with ScriptSessionLocal() as db:
                assert not await SUP.is_suppressed(db, email)
    finally:
        async with ScriptSessionLocal() as db:
            await db.execute(text("DELETE FROM email_suppressions WHERE email_lower = :e"), {"e": email})
            await db.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
            await db.commit()


@pytest.mark.asyncio
async def test_an_inactive_recipient_refusal_is_raised_for_the_caller_to_record(monkeypatch):
    class R:
        status_code = 422

        def json(self):
            return {"ErrorCode": 406, "Message": "You tried to send to recipient(s) that have been marked as inactive."}

    class C:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): return R()

    monkeypatch.setattr(settings, "postmark_server_token", "t")
    monkeypatch.setattr(mailer.httpx, "AsyncClient", C)
    with pytest.raises(SUP.InactiveRecipient):
        await mailer.send(mailer.Message(to="a@b.c", subject="s", html="h", text="t", sign_in=True))


@pytest.mark.asyncio
async def test_sign_in_link_records_are_deleted_after_thirty_days():
    from datetime import datetime, timedelta, timezone
    from app.services import accounts as A
    now = datetime(2030, 3, 1, tzinfo=timezone.utc)
    async with ScriptSessionLocal() as db:
        await db.execute(text("DELETE FROM auth_links WHERE email_lower LIKE 'zz-linkage-%'"))
        await db.execute(text("""INSERT INTO auth_links (token_hash, email_lower, ip, created_at, expires_at) VALUES
            ('zzold', 'zz-linkage-old@example.com', NULL, :o, :o), ('zznew', 'zz-linkage-new@example.com', NULL, :n, :n)"""),
                         {"o": now - timedelta(days=31), "n": now - timedelta(days=29)})
        await db.commit()
        try:
            assert await A.delete_old_links(db, now) >= 1
            await db.commit()
            left = set((await db.execute(text("SELECT email_lower FROM auth_links WHERE email_lower LIKE 'zz-linkage-%'"))).scalars())
            assert left == {"zz-linkage-new@example.com"}
        finally:
            await db.execute(text("DELETE FROM auth_links WHERE email_lower LIKE 'zz-linkage-%'"))
            await db.commit()
