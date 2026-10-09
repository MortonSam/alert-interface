"""The one way a pending cash deal is held (services/pending_deals): every row is checked against its SEC filing first.

Dry run by default: fetches the filing and prints each check. --write stores the row only when every check passed.
Checks: the ticker is active with a current security record; the filing is on EDGAR under the ticker's own CIK; it states the
cash price per share; it states the agreement date; it names every acquirer term. The evidence (the sentences that matched)
is stored with the row.

Usage:
    python -m app.scripts.set_pending_deal --symbol=AES --price=15.00 --acquirer="Global Infrastructure Partners and EQT" \\
        --terms="Global Infrastructure Partners,EQT" --agreed=2026-03-02 --expected-close="late 2026 or early 2027" \\
        --filing=https://www.sec.gov/Archives/edgar/data/874761/.../d100078ddefa14a.htm [--write]
    python -m app.scripts.set_pending_deal --symbol=AES --end=closed|terminated --on=2026-12-15 [--write]
"""
from __future__ import annotations

import asyncio
import re
import sys
from datetime import date, datetime, timezone

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services.edgar_client import USER_AGENT, EdgarClient
from app.services.pending_deals import fmt_price, note_for, Deal

WINDOW = 160        # characters around a match kept as evidence


def _arg(argv: list[str], name: str) -> str | None:
    return next((a.split("=", 1)[1] for a in argv if a.startswith(f"--{name}=")), None)


def cik_of_url(url: str) -> int | None:
    """Pure: the CIK in an EDGAR Archives URL."""
    m = re.search(r"/Archives/edgar/data/0*(\d+)/", url)
    return int(m.group(1)) if m else None


def squash(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


def find(body: str, pattern: str) -> str | None:
    """Pure: the text around the first match of `pattern`, or None."""
    m = re.search(pattern, body, re.I)
    if not m:
        return None
    return body[max(0, m.start() - WINDOW): m.end() + WINDOW].strip()


AGREEMENT_WORDS = r"(Agreement and Plan of Merger|Merger Agreement|merger agreement|entered into a definitive|definitive agreement)"
NEAR = 250


def find_near(body: str, pattern: str, near: str) -> str | None:
    """Pure: the text around the first match of `pattern` that has `near` within NEAR characters, or None."""
    for m in re.finditer(pattern, body, re.I):
        around = body[max(0, m.start() - NEAR): m.end() + NEAR]
        if re.search(near, around):
            return body[max(0, m.start() - WINDOW): m.end() + WINDOW].strip()
    return None


def price_pattern(price: float) -> str:
    """Pure: "$15.00 per share in cash" and the usual variants ("$15.00 in cash per share", "$15.00 per share, in cash")."""
    p = re.escape(f"{price:,.2f}")
    return rf"\$\s?{p}\s*(?:per\s+share[\s,]*(?:of\s+[\w\s]{{0,40}}?)?(?:,\s*)?(?:payable\s+)?in\s+cash|in\s+cash[\s,]*(?:,\s*)?per\s+share)"


def date_pattern(d: date) -> str:
    return rf"{d.strftime('%B')}\s+{d.day},\s+{d.year}"


def checks(body: str, price: float, agreed: date, terms: list[str]) -> list[tuple[str, bool, str]]:
    """Pure: (check, passed, evidence) for the filing text."""
    out = []
    ev = find(body, price_pattern(price))
    out.append((f"states {fmt_price(price)} per share in cash", ev is not None, ev or "no match"))
    ev = find_near(body, date_pattern(agreed), AGREEMENT_WORDS)
    out.append((f"states the agreement date {agreed.strftime('%B')} {agreed.day}, {agreed.year} beside the merger agreement", ev is not None, ev or "no match"))
    for t in terms:
        ev = find(body, re.escape(t))
        out.append((f"names {t}", ev is not None, ev or "no match"))
    return out


async def run(argv: list[str]) -> int:
    write = "--write" in argv
    sym = (_arg(argv, "symbol") or "").upper()
    if not sym:
        print(__doc__); return 2
    end = _arg(argv, "end")
    async with ScriptSessionLocal() as s:
        if end:
            if end not in ("closed", "terminated"):
                print("--end must be closed or terminated"); return 2
            on = date.fromisoformat(_arg(argv, "on") or date.today().isoformat())
            row = (await s.execute(text("SELECT id, price_per_share FROM pending_deals WHERE symbol = :s AND status = 'active'"), {"s": sym})).first()
            print(f"{sym}: active row {'found' if row else 'not found'}; would mark it {end} on {on}")
            if row and write:
                await s.execute(text("UPDATE pending_deals SET status = :st, ended_on = :on, updated_at = now() WHERE id = :id"), {"st": end, "on": on, "id": row[0]})
                await s.commit(); print("written")
            return 0 if row else 1
        price, agreed, filing = float(_arg(argv, "price") or 0), date.fromisoformat(_arg(argv, "agreed") or "1900-01-01"), _arg(argv, "filing") or ""
        acquirer, expected = _arg(argv, "acquirer") or "", _arg(argv, "expected-close")
        terms = [t.strip() for t in (_arg(argv, "terms") or acquirer).split(",") if t.strip()]
        rec = (await s.execute(text("""SELECT t.is_active, sr.id FROM tickers t LEFT JOIN security_records sr ON sr.symbol = t.symbol AND sr.role = 'current'
            WHERE t.symbol = :s"""), {"s": sym})).first()
        existing = (await s.execute(text("SELECT price_per_share, acquirer FROM pending_deals WHERE symbol = :s AND status = 'active'"), {"s": sym})).first()
    results: list[tuple[str, bool, str]] = []
    results.append(("ticker is active with a current security record", bool(rec and rec[0] and rec[1]), f"active={rec[0] if rec else None}, record={rec[1] if rec else None}"))
    results.append(("no active row already holds it", existing is None, f"existing: {existing[1]} at {fmt_price(float(existing[0]))}" if existing else "none"))
    results.append(("a positive cash price and an agreement date", price > 0 and agreed.year > 1900, f"price {price}, agreed {agreed}"))
    edgar = EdgarClient()
    try:
        cik = await edgar.get_cik(sym)
    finally:
        await edgar.close()
    url_cik = cik_of_url(filing)
    results.append(("filing is on EDGAR under the ticker's own CIK", filing.startswith("https://www.sec.gov/Archives/") and cik is not None and url_cik == int(cik),
                    f"ticker CIK {cik}, filing CIK {url_cik}"))
    body = ""
    try:
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True) as c:
            r = await c.get(filing)
            r.raise_for_status()
            body = squash(BeautifulSoup(r.text, "html.parser").get_text(" "))
        results.append(("filing fetched", True, f"{len(body):,} characters of text"))
    except Exception as exc:
        results.append(("filing fetched", False, type(exc).__name__))
    if body:
        results += checks(body, price, agreed, terms)
    ok = all(passed for _, passed, _ in results)
    print(f"{sym}: {fmt_price(price)} cash, {acquirer}, agreed {agreed}, expected close {expected or 'not stated'}")
    print(f"filing {filing}")
    for name, passed, ev in results:
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
        print(f"        {ev[:420]}")
    deal = Deal(sym, price, acquirer, agreed, expected, filing)
    print(f"visitor note: {note_for(deal)}")
    if not ok:
        print("NOT WRITTEN: a check failed"); return 1
    if not write:
        print("dry run: nothing written (add --write)"); return 0
    evidence = " | ".join(f"{n}: {e[:400]}" for n, p, e in results if n.startswith(("states", "names")))
    async with ScriptSessionLocal() as s:
        await s.execute(text("""INSERT INTO pending_deals (symbol, security_record_id, price_per_share, consideration, acquirer, agreed_on, expected_close,
            filing_url, filing_evidence, filing_checked_at) VALUES (:s, :rid, :p, 'cash', :a, :ag, :ec, :f, :ev, :at)"""),
            {"s": sym, "rid": rec[1], "p": price, "a": acquirer, "ag": agreed, "ec": expected, "f": filing, "ev": evidence, "at": datetime.now(timezone.utc)})
        await s.commit()
    print("written")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
