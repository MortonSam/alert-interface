"""Email accounts (services/accounts), every route 404 while ACCOUNTS_ENABLED is off.

    POST   /account/sign-in              {email}: emails a one-use, 15-minute link (the same answer whether or not the address has an account)
    POST   /account/verify               {token}: spends the link, sets the session cookie
    GET    /account                      the signed-in person: email, email settings, saved counts
    PUT    /account/emails               {kind: on/off}: every email type, off until turned on
    POST   /account/import               {watchlist: [symbols], trades: [...]}: what this browser saved before signing in, moved in once
    POST   /account/sign-out             this device;  POST /account/sign-out-everywhere  every device
    DELETE /account                      the person and everything saved, in one step
    GET    /account/unsubscribe          ?u=&k=&s=: one click, signed, no sign-in needed (POST too: List-Unsubscribe-Post)
    GET    /account/trades/results       every saved idea and its hypothetical result, with the running summary
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.services import account_copy as K
from app.services import accounts as A

router = APIRouter(prefix="/account", tags=["account"])
IMPORT_MAX_SYMBOLS = 200
IMPORT_MAX_TRADES = 100


def _on() -> None:
    if not settings.accounts_enabled:
        raise HTTPException(status_code=404, detail="Not found")


async def signed_in(request: Request, db: AsyncSession = Depends(get_db)) -> str:
    _on()
    uid = await A.session_user(db, request.cookies.get(A.SESSION_COOKIE))
    if not uid:
        raise HTTPException(status_code=401, detail=K.API["sign_in_needed"])
    return uid


class SignIn(BaseModel):
    email: str


class Verify(BaseModel):
    token: str


@router.post("/sign-in", status_code=202)
async def sign_in(body: SignIn, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    _on()
    from app.services.draft_limiter import get_client_ip
    from app.services import mailer
    status_, token, email = await A.request_link(db, body.email, get_client_ip(request))
    if status_ == "invalid":
        raise HTTPException(status_code=422, detail=K.API["link_invalid"])
    if status_ == "limited":
        raise HTTPException(status_code=429, detail=K.API["link_limited"])
    url = f"{settings.site_url}/account/verify#t={token}"          # in the fragment: it never reaches a server log or a referrer
    m = K.SIGN_IN_EMAIL
    html_ = (f'<p style="font-size:16px">{m["lead"]}</p><p><a href="{url}" style="display:inline-block;padding:12px 20px;background:#f97316;color:#111;'
             f'border-radius:10px;text-decoration:none;font-weight:600">{m["button"]}</a></p><p style="font-size:13px;color:#666">{m["note"]}</p>'
             f'<p style="font-size:13px;color:#666">{K.NO_CALLS}<br>{settings.mailing_address}</p>')
    await mailer.send(mailer.Message(to=email, subject=m["subject"], sign_in=True, html=html_, text=f"{m['lead']}\n\n{url}\n\n{m['note']}\n\n{K.NO_CALLS}\n{settings.mailing_address}"))
    return {"detail": K.API["link_sent"]}


@router.post("/verify")
async def verify(body: Verify, response: Response, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    _on()
    session, uid, why = await A.use_link(db, body.token)
    if not session:
        raise HTTPException(status_code=400, detail=K.API[f"link_{why}"])
    response.set_cookie(value=session, **A.cookie_settings(secure=request.url.scheme == "https" or settings.site_url.startswith("https")))
    return {"signed_in": True}


@router.get("")
async def me(uid: str = Depends(signed_in), db: AsyncSession = Depends(get_db)) -> dict:
    email = (await db.execute(text("SELECT email_lower FROM users WHERE id = :u"), {"u": uid})).scalar()
    prefs = {r.kind: r.enabled for r in (await db.execute(text("SELECT kind, enabled FROM email_prefs WHERE user_id = :u"), {"u": uid})).all()}
    return {"email": email, "emails": [{"kind": k, **v, "enabled": bool(prefs.get(k))} for k, v in K.KINDS.items()],
            "watchlist_count": (await db.execute(text("SELECT count(*) FROM watchlist_tickers wt JOIN watchlists w ON w.id = wt.watchlist_id WHERE w.user_id = :u"), {"u": uid})).scalar(),
            "trade_count": (await db.execute(text("SELECT count(*) FROM theses WHERE user_id = :u"), {"u": uid})).scalar()}


@router.put("/emails")
async def set_emails(body: dict[str, bool], uid: str = Depends(signed_in), db: AsyncSession = Depends(get_db)) -> dict:
    for kind, on in body.items():
        if kind not in K.KINDS:
            raise HTTPException(status_code=422, detail=f"unknown email {kind}")
        await db.execute(text("""INSERT INTO email_prefs (user_id, kind, enabled, updated_at) VALUES (:u, :k, :e, now())
            ON CONFLICT (user_id, kind) DO UPDATE SET enabled = EXCLUDED.enabled, updated_at = now()"""), {"u": uid, "k": kind, "e": bool(on)})
    await db.commit()
    return await me(uid, db)


class Import(BaseModel):
    watchlist: list[str] = []
    trades: list[dict] = []


@router.post("/import")
async def import_local(body: Import, uid: str = Depends(signed_in), db: AsyncSession = Depends(get_db)) -> dict:
    """What this browser saved before signing in, moved into the account (Sam, 2026-10-29): watchlist symbols join the person's
    first watchlist (made when they have none), each once. Saved trades here are only ever made signed in, so none come this way."""
    from app.models.watchlist import Watchlist
    symbols = list(dict.fromkeys(s.strip().upper() for s in body.watchlist[:IMPORT_MAX_SYMBOLS] if s and s.strip()))
    added = 0
    if symbols:
        wl = (await db.execute(select(Watchlist).where(Watchlist.user_id == uid).order_by(Watchlist.created_at))).scalars().first()
        if wl is None:
            wl = Watchlist(user_id=uid, name="My watchlist")
            db.add(wl)
            await db.flush()
        added = (await db.execute(text("""INSERT INTO watchlist_tickers (id, watchlist_id, ticker_id, added_at)
            SELECT gen_random_uuid(), :w, t.id, now() FROM tickers t WHERE t.symbol = ANY(:s) AND t.is_active
            ON CONFLICT (watchlist_id, ticker_id) DO NOTHING"""), {"w": wl.id, "s": symbols})).rowcount
        await db.commit()
    return {"watchlist_added": added, "trades_added": 0}


@router.post("/sign-out")
async def sign_out(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    _on()
    await A.sign_out(db, request.cookies.get(A.SESSION_COOKIE))
    response.delete_cookie(A.SESSION_COOKIE, path="/")
    return {"detail": K.API["signed_out"]}


@router.post("/sign-out-everywhere")
async def sign_out_everywhere(request: Request, response: Response, uid: str = Depends(signed_in), db: AsyncSession = Depends(get_db)) -> dict:
    await A.sign_out(db, request.cookies.get(A.SESSION_COOKIE), everywhere=True)
    response.delete_cookie(A.SESSION_COOKIE, path="/")
    return {"detail": K.API["signed_out_everywhere"]}


@router.delete("")
async def delete_me(response: Response, uid: str = Depends(signed_in), db: AsyncSession = Depends(get_db)) -> dict:
    await A.delete_account(db, uid)
    response.delete_cookie(A.SESSION_COOKIE, path="/")
    return {"detail": K.API["deleted"]}


@router.api_route("/unsubscribe", methods=["GET", "POST"])
async def unsubscribe(u: str, k: str, s: str, db: AsyncSession = Depends(get_db)) -> dict:
    _on()
    from app.services.emails import ALL
    if (k not in K.KINDS and k != ALL) or not A.unsubscribe_ok(settings.account_secret, u, k, s):
        raise HTTPException(status_code=400, detail=K.API["unsubscribe_bad"])
    if k == ALL:
        await db.execute(text("UPDATE email_prefs SET enabled = false, updated_at = now() WHERE user_id = :u"), {"u": u})
    else:
        await db.execute(text("UPDATE email_prefs SET enabled = false, updated_at = now() WHERE user_id = :u AND kind = :k"), {"u": u, "k": k})
    await db.commit()
    return {"detail": K.API["unsubscribed_all"] if k == ALL else K.API["unsubscribed"].format(kind=K.KINDS[k]["name"])}


@router.get("/trades/results")
async def trade_results(uid: str = Depends(signed_in), db: AsyncSession = Depends(get_db)) -> dict:
    from app.services.trade_results import summary_line
    rows = (await db.execute(text("""SELECT th.id, t.symbol, th.option_type, th.strike, th.strike2, th.option_expiration, th.created_at, th.result
        FROM theses th JOIN tickers t ON t.id = th.ticker_id WHERE th.user_id = :u AND th.option_type IS NOT NULL ORDER BY th.option_expiration DESC"""), {"u": uid})).all()
    items = [{"id": str(r.id), "symbol": r.symbol, "option_type": r.option_type, "strike": float(r.strike) if r.strike is not None else None,
              "strike2": float(r.strike2) if r.strike2 is not None else None, "expiration": r.option_expiration.isoformat() if r.option_expiration else None,
              "saved_on": r.created_at.date().isoformat(), "result": r.result} for r in rows]
    scored = [i["result"] for i in items if i["result"]]
    return {"label": "Hypothetical", "summary": summary_line(scored) if scored else None, "items": items}
