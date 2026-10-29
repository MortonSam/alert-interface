"""Accounts (Sam, 2026-10-29), behind ACCOUNTS_ENABLED: magic-link sign-in (15 minutes, once, rate limited per email and per IP),
sessions in a secure cookie, sign out everywhere, delete everything in one step; reading stays open and Ask Ivy needs sign-in; the
emails follow the rules (opt-in, one a day, every footer, no buy-or-sell words); hypothetical trade results scored from past chains."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.config import settings
from app.database import ScriptSessionLocal
from app.services import account_copy as K
from app.services import accounts as A
from app.services import emails as E
from app.services import trade_results as T

pytestmark = pytest.mark.xdist_group(name="accounts")
NOW = datetime(2026, 10, 29, 15, 0, tzinfo=timezone.utc)


# ── sign-in rules ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_an_address_is_compared_trimmed_and_lower_case():
    assert A.normalize_email("  Sam@Example.COM ") == "sam@example.com"
    assert A.normalize_email("not an email") is None and A.normalize_email("a@b") is None and A.normalize_email(None) is None


def test_a_link_works_once_for_fifteen_minutes():
    link = SimpleNamespace(used_at=None, expires_at=NOW + timedelta(minutes=A.LINK_MINUTES))
    assert A.judge_link(link, NOW).ok and A.LINK_MINUTES == 15
    assert A.judge_link(link, NOW + timedelta(minutes=15)).why == "expired"
    assert A.judge_link(SimpleNamespace(used_at=NOW, expires_at=NOW + timedelta(minutes=5)), NOW).why == "used"
    assert A.judge_link(None, NOW).why == "unknown"
    assert A.token_hash("x") != "x" and len(A.token_hash("x")) == 64


def test_requests_are_limited_per_email_and_per_ip():
    assert A.over_limits(0, 0, 0) is None
    assert A.over_limits(A.LINK_PER_EMAIL, 0, 0) == "email_window" and A.over_limits(0, A.LINK_PER_EMAIL_DAY, 0) == "email_day"
    assert A.over_limits(0, 0, A.LINK_PER_IP_HOUR) == "ip_hour"


def test_the_session_cookie_is_http_only_secure_and_same_site():
    c = A.cookie_settings()
    assert c["httponly"] and c["secure"] and c["samesite"] == "lax" and c["key"] == A.SESSION_COOKIE and c["max_age"] == 30 * 86400


def test_an_unsubscribe_link_is_signed():
    sig = A.unsubscribe_sig("s3cret", "acct_1", "earnings_eve")
    assert A.unsubscribe_ok("s3cret", "acct_1", "earnings_eve", sig)
    assert not A.unsubscribe_ok("s3cret", "acct_1", "morning_after", sig) and not A.unsubscribe_ok("", "acct_1", "earnings_eve", sig)


@pytest.mark.asyncio
async def test_sign_in_sign_out_everywhere_and_delete_everything():
    email = "zz-accounts-test@example.com"
    async with ScriptSessionLocal() as db:
        await db.execute(text("DELETE FROM auth_links WHERE email_lower = :e"), {"e": email})
        await db.execute(text("DELETE FROM users WHERE email_lower = :e"), {"e": email})
        await db.commit()
        try:
            st, token, _ = await A.request_link(db, email, "203.0.113.9", NOW)
            assert st == "sent" and token
            stored = (await db.execute(text("SELECT token_hash FROM auth_links WHERE email_lower = :e"), {"e": email})).scalar()
            assert stored == A.token_hash(token) and stored != token                    # only the hash is stored
            s1, uid, why = await A.use_link(db, token, NOW + timedelta(minutes=1))
            assert s1 and uid.startswith(A.ACCOUNT_PREFIX) and why is None
            assert (await A.use_link(db, token, NOW + timedelta(minutes=2)))[2] == "used"     # once
            st2, token2, _ = await A.request_link(db, email, "203.0.113.9", NOW + timedelta(minutes=3))
            s2, uid2, _ = await A.use_link(db, token2, NOW + timedelta(minutes=4))
            assert uid2 == uid                                                           # the same person
            st3, token3, _ = await A.request_link(db, email, "203.0.113.9", NOW + timedelta(minutes=5))
            assert st3 == "sent"
            assert (await A.request_link(db, email, "203.0.113.9", NOW + timedelta(minutes=6)))[0] == "limited"   # a 4th in 15 minutes
            assert (await A.use_link(db, token3, NOW + timedelta(minutes=30)))[2] == "expired"
            assert await A.session_user(db, s1, NOW + timedelta(minutes=10)) == uid
            assert await A.sign_out(db, s1, everywhere=True, now=NOW + timedelta(minutes=11)) == 2
            assert await A.session_user(db, s2, NOW + timedelta(minutes=12)) is None    # every device
            await db.execute(text("INSERT INTO email_prefs (user_id, kind, enabled) VALUES (:u, 'earnings_eve', true)"), {"u": uid})
            await db.execute(text("INSERT INTO watchlists (id, user_id, name) VALUES (gen_random_uuid(), :u, 'w')"), {"u": uid})
            await db.commit()
            removed = await A.delete_account(db, uid)
            assert removed["users"] == 1 and removed["email_prefs"] == 1 and removed["watchlists"] == 1 and removed["auth_links"] == 3   # its sign-in links too
            for table in A.PERSONAL_TABLES:
                assert (await db.execute(text(f"SELECT count(*) FROM {table} WHERE user_id = :u"), {"u": uid})).scalar() == 0
        finally:
            await db.execute(text("DELETE FROM auth_links WHERE email_lower = :e"), {"e": email})
            await db.execute(text("DELETE FROM users WHERE email_lower = :e"), {"e": email})
            await db.commit()


@pytest.mark.asyncio
async def test_delete_reaches_every_table_that_holds_a_persons_rows():
    async with ScriptSessionLocal() as db:
        tables = set((await db.execute(text("""SELECT table_name FROM information_schema.columns WHERE table_schema = 'public' AND column_name = 'user_id'"""))).scalars().all())
    assert tables <= set(A.PERSONAL_TABLES), tables - set(A.PERSONAL_TABLES)


@pytest.mark.asyncio
async def test_every_account_route_is_hidden_while_the_flag_is_off_and_asking_needs_sign_in(monkeypatch):
    from app.main import app
    monkeypatch.setattr(settings, "accounts_enabled", False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.post("/api/v1/account/sign-in", json={"email": "a@example.com"})).status_code == 404
        assert (await c.get("/api/v1/account")).status_code == 404
    sent = []

    async def capture(m):
        sent.append(m)
        return None
    from app.services import mailer
    monkeypatch.setattr(mailer, "send", capture)
    monkeypatch.setattr(settings, "accounts_enabled", True)
    monkeypatch.setattr(settings, "ask_ivy_enabled", True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://t") as c:
        r = await c.post("/api/v1/account/sign-in", json={"email": "zz-route-test@example.com"})
        assert r.status_code == 202 and r.json()["detail"] == K.API["link_sent"]
        assert (await c.post("/api/v1/account/sign-in", json={"email": "nope"})).status_code == 422
        token = sent[0].text.split("#t=")[1].split()[0]
        v = await c.post("/api/v1/account/verify", json={"token": token})
        assert v.status_code == 200 and A.SESSION_COOKIE in v.cookies
        me = await c.get("/api/v1/account")
        assert me.status_code == 200 and me.json()["email"] == "zz-route-test@example.com"
        assert all(not e["enabled"] for e in me.json()["emails"])                           # every email off until turned on
        assert (await c.post("/api/v1/account/verify", json={"token": token})).json()["detail"] == K.API["link_used"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://t") as anon:
        r = await anon.post("/api/v1/tickers/NVDA/ask", json={"question": "What does it sell?"})
        assert r.status_code == 401 and r.json()["detail"] == K.API["sign_in_needed"]
        assert (await anon.get("/api/v1/research-notes", params={"symbol": "NVDA"})).status_code in (200, 204)   # reading stays open
    async with ScriptSessionLocal() as db:
        uid = (await db.execute(text("SELECT id FROM users WHERE email_lower = 'zz-route-test@example.com'"))).scalar()
        await A.delete_account(db, uid)
        await db.execute(text("DELETE FROM auth_links WHERE email_lower = 'zz-route-test@example.com'"))
        await db.commit()


# ── the emails ────────────────────────────────────────────────────────────────────────────────────────────────────────────

SITE = "https://alertinterface.com"


def _email(sections):
    return E.merge(sections, site=SITE, unsubscribe={k: f"{SITE}/u/{k}" for k in [*K.KINDS, E.ALL]}, settings_url=f"{SITE}/account", mailing_address="MAILING_ADDRESS")


def test_every_fixed_word_follows_the_email_rules():
    words = list(K.API.values()) + [v for d in K.KINDS.values() for v in d.values()] + list(K.SIGN_IN_EMAIL.values()) + list(K.EMAIL.values())
    bad = [(w, E.problems(w)) for w in words if E.problems(w)]
    assert bad == []
    assert E.problems("Now is a good time to buy.") and E.problems("Last chance!") and E.problems(K.NO_CALLS) == []


def test_several_due_emails_merge_into_one_with_the_full_footer():
    confirmed = E.confirmed_section({"symbol": "NVDA", "name": "NVIDIA", "date": date(2026, 11, 17), "timing": "amc", "implied": (8.7, date(2026, 11, 20)), "typical": 6.6, "n": 20}, SITE)
    eve = E.eve_section({"symbol": "MSFT", "name": "Microsoft", "date": date(2026, 10, 30), "timing": "amc", "read": "A read.", "typical": 4.1, "n": 20}, SITE)
    em = _email([confirmed, eve])
    assert em.subject == "NVIDIA confirmed its report date and 1 more from Ivy" and em.kinds == ["date_confirmed", "earnings_eve"]
    assert "NVIDIA reports on Tue, Nov 17, 2026, after the market closes, a date the company has confirmed." in em.text
    assert "Options price a move of about ±8.7% by Nov 20, 2026, the first expiration after the report, more than its typical ±6.6% on a report day." in em.text
    assert f"{SITE}/u/all" in em.text and "You get this because you turned on Date confirmed and Earnings eve in your settings." in em.text
    for must in (K.NO_CALLS, K.EMAIL["footer_unsubscribe_all"], K.EMAIL["footer_settings"], "MAILING_ADDRESS", K.EMAIL["footer_one_a_day"]):
        assert must in em.text and must in em.html
    assert f"{SITE}/tickers/NVDA" in em.html and 'name="viewport"' in em.html and E.email_problems(em) == []
    assert E.eve_section({"symbol": "X", "name": "X", "date": date(2026, 10, 30), "timing": None}, SITE) is None   # the eve states the time
    assert _email([]) is None


def test_the_morning_after_and_the_week():
    trades = [{"label": "The Nov 20 $200 call", "result": T.score(option_type="call", strike=200, entry_premium=5.0, contracts=1, close_at_expiration=212.0,
                                                                   entry_price=198.0, expiration=date(2026, 11, 20), saved_on=date(2026, 10, 1))}]
    a = E.after_section({"symbol": "NVDA", "name": "NVIDIA", "session": date(2026, 11, 18), "move": -4.2, "implied": 7.4,
                         "history": [(5.0, 7.0), (-9.0, 6.5), (2.0, 6.0)], "trades": trades}, SITE)
    t = "\n".join(a.lines)
    assert "NVIDIA fell 4.2% on Wed, Nov 18, 2026, the first session after its report." in t
    assert "Options had priced a move of about ±7.4%, so it moved less than options priced." in t
    assert "In 1 of its last 3 reports on file, it moved more than options priced." in t
    assert "cost $500.00, worth $1,200.00 at expiration, ahead by $700.00 (140.0%)." in t and K.EMAIL["hypothetical"] in t
    w = E.week_section([{"symbol": f"S{i}", "name": f"Co {i}", "date": date(2026, 11, 2), "timing": "bmo"} for i in range(12)],
                       [{"symbol": "S11", "name": "Co 11", "date": date(2026, 11, 2), "timing": "bmo"}], date(2026, 11, 2), date(2026, 11, 6), SITE)
    assert sum(1 for ln in w.lines if ln.startswith("Co ")) == 10 + 1 and w.title == "This week's earnings, Nov 2, 2026 to Nov 6, 2026"
    assert E.email_problems(_email([a, w])) == []


# ── hypothetical results, with past chains ────────────────────────────────────────────────────────────────────────────────

CHAIN = {"underlying_price": 200.0,
         "calls": [{"strike": 195.0, "bid": 9.6, "ask": 10.0}, {"strike": 200.0, "bid": 6.9, "ask": 7.1}, {"strike": 210.0, "bid": 3.0, "ask": 3.2}],
         "puts": [{"strike": 195.0, "bid": 4.4, "ask": 4.6}, {"strike": 200.0, "bid": 6.8, "ask": 7.2}, {"strike": 210.0, "bid": 12.9, "ask": 13.3}]}


def test_a_saved_idea_is_scored_at_expiration_against_what_options_priced():
    from app.services.implied_move import straddle_implied_move
    priced = round(straddle_implied_move(CHAIN["calls"], CHAIN["puts"], CHAIN["underlying_price"]).pct * 100, 1)
    assert priced == 7.0                                                         # (7.0 + 7.0) / 200
    call = T.score(option_type="call", strike=200, entry_premium=7.0, contracts=2, close_at_expiration=209.0, entry_price=200.0,
                   priced_move_pct=priced, expiration=date(2026, 11, 20), saved_on=date(2026, 10, 20))
    assert (call["paid_usd"], call["worth_usd"], call["result_usd"], call["result_pct"], call["ahead"]) == (1400.0, 1800.0, 400.0, 28.57, True)
    assert call["stock_move_pct"] == 4.5 and call["moved_vs_priced"] == "less"
    put = T.score(option_type="put", strike=200, entry_premium=7.0, contracts=1, close_at_expiration=209.0, entry_price=200.0,
                  priced_move_pct=priced, expiration=date(2026, 11, 20), saved_on=date(2026, 10, 20))
    assert put["worth_usd"] == 0.0 and put["result_usd"] == -700.0 and not put["ahead"]
    spread = T.score(option_type="call", strike=200, entry_premium=7.0, strike2=210, entry_premium2=3.1, contracts=1, close_at_expiration=230.0,
                     entry_price=200.0, priced_move_pct=priced, expiration=date(2026, 11, 20), saved_on=date(2026, 10, 20))
    assert spread["paid_usd"] == 390.0 and spread["worth_usd"] == 1000.0 and spread["moved_vs_priced"] == "more"     # capped at the width
    assert T.summary_line([call, put, spread]) == "3 hypothetical trades, 2 finished ahead"
    assert T.summary_line([call]) == "1 hypothetical trade, 1 finished ahead"
