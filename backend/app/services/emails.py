"""The opted-in emails (Sam, 2026-10-29), built only from data the site already stores and held to the pages' rules.

    date_confirmed  a followed stock's report date became company-confirmed: the date, the timing, and what options price for it
                    against its typical move when both are on file
    earnings_eve    a followed stock reports the next trading day: Ivy's Read (the page's own, services/ivy_read_plain), its typical
                    report move and the confirmed time
    morning_after   a followed stock's first session after its report has closed: how much it moved, what options had priced, more
                    or less than priced (move_comparison's rule), how often it moved more than priced in its reports on file, and the
                    person's hypothetical trades on it that expired (services/trade_results)
    earnings_week   Sundays: the week's ten largest reporters by market value, one line each with its page, and the person's followed
                    stocks reporting that week

One email a day at most: the day's due kinds merge into one (merge). It goes out once a day at SEND_HOUR New York, after the nightly
has stored the previous session's closes. Every email is plain HTML that reads on a phone, links each company's page, comes from
"Ivy at Alert Interface", and ends with the footer: why it came, one-click unsubscribe, settings, the mailing address and "Ivy
doesn't make buy or sell calls." No sentence may say or imply buy, sell or what to do, or press (problems; tested on every kind).
A kind with nothing true to say for a person that day sends nothing.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.services import account_copy as K

SEND_HOUR = 18
ALL = "all"                      # the unsubscribe key for a merged email: it turns off every kind the person has on
WEEK_TOP = 10
AFTER_HISTORY_MIN = 4            # the morning-after tally of past reports is shown from this many on file; with fewer the line is left out
ADVICE = re.compile(r"\b(?:buy|sell|sold|bought|hold(?:ing)? on|should|consider|opportunit\w*|act now|don't miss|last chance|hurry|"
                    r"limited time|before it'?s too late|time to|recommend\w*|target price|upside|downside|entry|exit)\b", re.I)
URGENCY = re.compile(r"\b(?:now|today only|ends|countdown|last chance|only \d+ left|expires? soon)\b|!", re.I)


@dataclass
class Section:
    kind: str
    title: str
    lines: list[str]
    links: list[tuple[str, str]] = field(default_factory=list)      # (label, url)
    items: list[dict] = field(default_factory=list)                 # what it reported on, for the send log (no repeats)
    line_urls: dict[int, str] = field(default_factory=dict)         # a line that is itself the link to its company's page


@dataclass
class Email:
    subject: str
    html: str
    text: str
    kinds: list[str]
    items: list[dict]


def problems(text_: str) -> list[str]:
    """Pure: why a sentence may not be sent: advice, a what-to-do word or urgency. NO_CALLS, the footer's own line, is the exception."""
    t = text_.replace(K.NO_CALLS, "")
    out = []
    m = ADVICE.search(t)
    if m:
        out.append(f"advice or what to do: {m.group(0)}")
    m = URGENCY.search(t)
    if m:
        out.append(f"urgency: {m.group(0)}")
    return out


def pct(x: float) -> str:
    return f"{abs(x):,.1f}"


def day_words(d: date) -> str:
    from app.services.briefing import fmt_date
    return d.strftime("%a, ") + fmt_date(d)


def moved(x: float) -> str:
    return f"rose {pct(x)}%" if x > 0 else f"fell {pct(x)}%" if x < 0 else "was unchanged"


def page_url(site: str, symbol: str) -> str:
    return f"{site}/tickers/{symbol}"


UTM_SOURCE = "alertinterface_email"


def tag(url: str, kind: str) -> str:
    """Pure: a link to the site with the tags its analytics reads (utm_source, utm_medium, utm_campaign = the email type); Postmark's
    own link tracking is off (services/mailer), so these are the only record of a click, and only after the visitor's consent."""
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}utm_source={UTM_SOURCE}&utm_medium=email&utm_campaign={kind}"


# ── the four kinds, from facts (pure) ─────────────────────────────────────────────────────────────────────────────────────

def confirmed_section(f: dict, site: str) -> Section:
    """f: {symbol, name, date, timing, implied: (percent, expiration) or None, report: {pct, verdict} or None, typical, n}. Like with
    like (Sam, 2026-11-03, the walkthrough's rule): only the report's own share of the move (services/report_move, as Ivy's Read states
    it) is compared with the typical report-day move; the straddle runs to the first expiration after the report, so it is stated "by"
    that day, with no comparison, and the typical move follows on its own line."""
    from app.services.briefing import fmt_date
    lines = [K.EMAIL["confirmed_line"].format(name=f["name"], day=day_words(f["date"]), timing=K.TIMING.get(f.get("timing") or "", ""))]
    rep = f.get("report") or {}
    if rep.get("pct") is not None and rep.get("verdict") and f.get("typical") is not None:
        lines.append(K.EMAIL["confirmed_options"].format(report=pct(rep["pct"]), typical=pct(f["typical"]), cmp=K.COMPARE[rep["verdict"]]))
    else:
        if f.get("implied"):
            im, exp = f["implied"]
            lines.append(K.EMAIL["confirmed_options_term"].format(implied=pct(im), expiration=fmt_date(exp)))
        if f.get("typical") is not None:
            lines.append(K.EMAIL["confirmed_typical"].format(n=f["n"], typical=pct(f["typical"])))
    return Section("date_confirmed", K.EMAIL["confirmed_title"].format(name=f["name"]), lines,
                   [(K.EMAIL["open_page"].format(name=f["name"]), page_url(site, f["symbol"]))], [{"kind": "date_confirmed", "symbol": f["symbol"], "date": f["date"].isoformat()}])


def eve_section(f: dict, site: str) -> Section | None:
    """f: {symbol, name, date, timing, read, typical, n}; None without a company-confirmed time (the eve email states the time)."""
    if f.get("timing") not in K.TIMING:
        return None
    when = "tomorrow, " + day_words(f["date"])
    lines = [K.EMAIL["eve_line"].format(name=f["name"], when=when, timing=K.TIMING[f["timing"]])]
    if f.get("typical") is not None:
        lines.append(K.EMAIL["eve_typical"].format(n=f["n"], typical=pct(f["typical"])))
    if f.get("read"):
        lines.append(f"{K.EMAIL['eve_read_lead']}. {f['read']}")
    return Section("earnings_eve", K.EMAIL["eve_title"].format(name=f["name"], when="tomorrow"), lines,
                   [(K.EMAIL["open_page"].format(name=f["name"]), page_url(site, f["symbol"]))], [{"kind": "earnings_eve", "symbol": f["symbol"], "date": f["date"].isoformat()}])


def after_section(f: dict, site: str) -> Section | None:
    """f: {symbol, name, session, move, implied, history: [(move, implied)] of the reports before this one, trades: [result dict +
    label]}; None without the move. The tally of past reports needs AFTER_HISTORY_MIN of them with both figures on file."""
    if f.get("move") is None:
        return None
    lines = [K.EMAIL["after_move"].format(name=f["name"], moved=moved(f["move"]), day=day_words(f["session"]))]
    if f.get("implied"):
        from app.services.move_comparison import compare_moves
        word = compare_moves(abs(f["move"]), f["implied"])
        lines.append(K.EMAIL["after_vs_priced"].format(implied=pct(f["implied"]), cmp=K.COMPARE[word]))
    hist = [(m, i) for m, i in f.get("history") or [] if m is not None and i]
    if len(hist) >= AFTER_HISTORY_MIN:          # "In 0 of its last 1 reports" says nothing (Sam, 2026-11-10)
        lines.append(K.EMAIL["after_history"].format(k=sum(1 for m, i in hist if abs(m) > i), n=len(hist)))
    for t in f.get("trades") or []:
        r = t["result"]
        res = (f"ahead by ${r['result_usd']:,.2f} ({pct(r['result_pct'] or 0)}%)" if r["result_usd"] > 0 else
               f"behind by ${abs(r['result_usd']):,.2f} ({pct(r['result_pct'] or 0)}%)" if r["result_usd"] < 0 else "even")
        lines.append(K.EMAIL["after_trade"].format(label=t["label"], saved=day_words(date.fromisoformat(r["saved_on"])), cost=f"${r['paid_usd']:,.2f}",
                                                   worth=f"${r['worth_usd']:,.2f}", result=res))
    if f.get("trades"):
        lines.append(K.EMAIL["hypothetical"])
    return Section("morning_after", K.EMAIL["after_title"].format(name=f["name"]), lines,
                   [(K.EMAIL["open_page"].format(name=f["name"]), page_url(site, f["symbol"]))],
                   [{"kind": "morning_after", "symbol": f["symbol"], "date": f["session"].isoformat()}])


def week_section(top: list[dict], yours: list[dict], start: date, end: date, site: str) -> Section | None:
    """top / yours: [{symbol, name, date, timing}]; None when nothing reports."""
    if not top and not yours:
        return None
    from app.services.briefing import fmt_date
    line = lambda f: K.EMAIL["week_line"].format(name=f["name"], day=day_words(f["date"]), timing=K.TIMING.get(f.get("timing") or "", ""))
    lines, urls = [K.EMAIL["week_lead"]], {}
    for f in top[:WEEK_TOP]:
        urls[len(lines)] = page_url(site, f["symbol"]); lines.append(line(f))
    if yours:
        lines.append(K.EMAIL["week_yours"])
        for f in yours:
            urls[len(lines)] = page_url(site, f["symbol"]); lines.append(line(f))
    return Section("earnings_week", K.EMAIL["week_title"].format(start=fmt_date(start), end=fmt_date(end)), lines, [],
                   [{"kind": "earnings_week", "date": start.isoformat()}], urls)


# ── one email ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

def merge(sections: list[Section], *, site: str, unsubscribe: dict[str, str], settings_url: str, mailing_address: str) -> Email | None:
    """Pure: the day's sections in one email (None when there are none). unsubscribe: {kind: its one-click url}."""
    sections = [s for s in sections if s]
    if not sections:
        return None
    kinds = list(dict.fromkeys(s.kind for s in sections))
    subject = (K.EMAIL["subject_one"].format(title=sections[0].title) if len(sections) == 1 else
               K.EMAIL["subject_many"].format(first=sections[0].title, n=len(sections) - 1))
    names = [K.KINDS[k]["name"] for k in kinds]
    kind_names = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    e = lambda t: html.escape(t, quote=False)          # text; an href is escaped in full (h)
    h = html.escape
    body = [f'<p style="margin:0 0 16px;font-size:16px;line-height:1.5">{e(K.EMAIL["greeting"])}</p>']
    text_ = [K.EMAIL["greeting"], ""]
    for s in sections:
        body.append(f'<h2 style="margin:24px 0 8px;font-size:19px;line-height:1.3;font-weight:600">{e(s.title)}</h2>')
        text_ += [s.title, ""]
        for i, ln in enumerate(s.lines):
            url = tag(s.line_urls[i], s.kind) if i in s.line_urls else None
            inner = f'<a href="{h(url)}" style="color:#111">{e(ln)}</a>' if url else e(ln)
            body.append(f'<p style="margin:0 0 10px;font-size:16px;line-height:1.5">{inner}</p>')
            text_.append(f"{ln} {url}" if url else ln)
        for label, url in ((lb, tag(u, s.kind)) for lb, u in s.links):
            body.append(f'<p style="margin:0 0 8px;font-size:15px"><a href="{h(url)}" style="color:#c2410c">{e(label)} →</a></p>')
            text_.append(f"{label}: {url}")
        text_.append("")
    unsub = (unsubscribe.get(kinds[0]) if len(kinds) == 1 else unsubscribe.get(ALL)) or settings_url      # one click turns off what came
    unsub_label = K.EMAIL["footer_unsubscribe"] if len(kinds) == 1 else K.EMAIL["footer_unsubscribe_all"]
    foot = [K.EMAIL["footer_why"].format(kinds=kind_names), K.EMAIL["footer_one_a_day"], K.NO_CALLS, mailing_address]
    body.append('<hr style="border:none;border-top:1px solid #e5e5e5;margin:28px 0 14px">')
    for ln in foot:
        body.append(f'<p style="margin:0 0 6px;font-size:13px;line-height:1.5;color:#666">{e(ln)}</p>')
    body.append(f'<p style="margin:8px 0 0;font-size:13px;color:#666"><a href="{h(unsub)}" style="color:#666">{e(unsub_label)}</a>'
                f' · <a href="{h(settings_url)}" style="color:#666">{e(K.EMAIL["footer_settings"])}</a></p>')
    text_ += ["--"] + foot + [f"{unsub_label}: {unsub}", f"{K.EMAIL['footer_settings']}: {settings_url}"]
    doc = ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           f'<title>{e(subject)}</title></head><body style="margin:0;padding:0;background:#ffffff">'
           '<div style="max-width:560px;margin:0 auto;padding:24px 18px;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif;color:#111">'
           f'<p style="margin:0 0 18px;font-size:13px;color:#666">{e(K.SENDER_NAME)}</p>' + "".join(body) + "</div></body></html>")
    return Email(subject, doc, "\n".join(text_), kinds, [i for s in sections for i in s.items])


def email_problems(em: Email) -> list[str]:
    """Pure: every sentence of the email that breaks the rules (the subject included)."""
    out = []
    for ln in [em.subject] + em.text.splitlines():
        words = re.sub(r"https?://\S+", "", ln)                       # a link's address is not a sentence
        out += [f"{ln[:80]}: {p}" for p in problems(words)]
    if K.NO_CALLS not in em.text:
        out.append("the footer lacks the no-buy-or-sell line")
    return out


# ── facts from the stored tables ──────────────────────────────────────────────────────────────────────────────────────────

async def typical_move(db, ticker_id) -> tuple[float | None, int]:
    from sqlalchemy import text
    from app.services.basis_exclusion import basis_mismatch_dates
    mismatch = await basis_mismatch_dates(db, ticker_id)
    rows = (await db.execute(text("""SELECT event_date, pct_change_1d FROM historical_reactions WHERE ticker_id = :t AND event_type = 'earnings'
        AND pct_change_1d IS NOT NULL"""), {"t": ticker_id})).all()
    vals = [abs(float(m)) for d, m in rows if d not in mismatch]
    return (round(sum(vals) / len(vals), 1), len(vals)) if vals else (None, 0)


async def implied_for_report(db, symbol: str, report_date: date, today: date) -> tuple[float, date] | None:
    """(percent, expiration): the straddle on the first stored expiration that captures the report, while the chain is fresh."""
    from app.services import chain_store
    from app.services.implied_move import straddle_implied_move
    exp = await chain_store.pick_expiration(db, symbol, report_date.isoformat())
    got = await chain_store.get_chain(db, symbol, exp) if exp else None
    if not got or not got[1] or not chain_store.is_fresh(got[1], today=today):
        return None
    spot = got[0].get("underlying_price")
    im = straddle_implied_move(got[0].get("calls") or [], got[0].get("puts") or [], float(spot)) if spot else None
    return (round(im.pct * 100, 1), date.fromisoformat(exp)) if im else None


async def report_share(db, symbol: str, report_date: date, today: date, typical: float | None, n: int) -> dict | None:
    """{pct, verdict}: the report's own share of the move options price and its comparison words against the typical report-day
    move, as Ivy's Read states them (services/report_move.report_move_view); None when either is not on file."""
    from app.services.report_move import report_move_view
    v = await report_move_view(db, symbol, report_date, today, typical=(typical, n) if typical is not None else (None, 0))
    return {"pct": v["rep"], "verdict": v.get("move_comparison")} if v.get("rep") is not None and v.get("move_comparison") else None


def priced_before_report(hist: dict, report_date: date, timing: str | None) -> float | None:
    """Pure: the report move options priced, in percent, on the newest chain on file from before the report, never one taken after it
    (Sam, 2026-11-10). The history keeps each chain's move as a fraction (report_move.ReportMove.pct, 0.077 for 7.7%). A chain
    of the report day itself counts only for a report after the close (its closing prices precede the release); a report before the
    open, or at an unknown time, counts only chains of earlier days."""
    last = report_date.isoformat()
    ok = lambda d: d < last or (d == last and timing == "amc")
    before = [(d, h["pct"]) for d, h in sorted(hist.items()) if ok(d) and h.get("pct") is not None]
    return round(float(before[-1][1]) * 100, 1) if before else None


async def priced_before(db, symbol: str, report_date: date, timing: str | None) -> float | None:
    """The report move options priced before the report (priced_before_report over services/report_move's stored history)."""
    import json
    from app.services.report_move import history_key
    from app.services.system_metadata_service import get_value
    return priced_before_report(json.loads(await get_value(db, history_key(symbol, report_date.isoformat())) or "{}"), report_date, timing)


async def first_session_move(db, symbol: str, report_date: date, timing: str | None) -> tuple[date | None, float | None]:
    """(the first session after the report, its close-to-close move in percent) from the stored closes: a before-open report moves
    on its own day, any other on the next session."""
    from app.services import price_bars
    from app.services.trading_calendar import last_session_before, nth_trading_day_after
    if timing == "bmo":
        session, prev = report_date, last_session_before(report_date)
    else:
        session, prev = nth_trading_day_after(report_date, 1), report_date
    a, b = price_bars.close_on_date_sync(symbol, prev.isoformat()), price_bars.close_on_date_sync(symbol, session.isoformat())
    if a is None or b is None or a <= 0:
        return session, None
    return session, round((b / a - 1) * 100, 1)


async def followed(db, user_id: str) -> list[dict]:
    """The stocks a person follows: every stock on their watchlists, once."""
    from sqlalchemy import text
    rows = (await db.execute(text("""SELECT DISTINCT t.id, t.symbol, t.name FROM watchlists w JOIN watchlist_tickers wt ON wt.watchlist_id = w.id
        JOIN tickers t ON t.id = wt.ticker_id WHERE w.user_id = :u AND t.is_active ORDER BY t.symbol"""), {"u": user_id})).all()
    return [dict(r._mapping) for r in rows]


async def sent_items(db, user_id: str) -> set[tuple]:
    """(kind, symbol, date) of everything already emailed to the person, so nothing is told twice."""
    from sqlalchemy import text
    rows = (await db.execute(text("SELECT items FROM email_sends WHERE user_id = :u AND items IS NOT NULL"), {"u": user_id})).scalars().all()
    return {(i.get("kind"), i.get("symbol"), i.get("date")) for items in rows for i in (items or [])}


async def report_timing(db, ticker_id, d: date) -> str | None:
    from sqlalchemy import text
    return (await db.execute(text("SELECT report_timing::text FROM events WHERE ticker_id = :t AND event_type = 'earnings' AND event_date = :d LIMIT 1"),
                             {"t": ticker_id, "d": d})).scalar()


async def sections_for(db, user_id: str, kinds: set[str], today: date, site: str) -> list[Section]:
    """The day's sections for one person and the kinds they turned on."""
    from app.services.briefing import short_name
    from app.services.next_earnings import batch_next_earnings
    from app.services.trading_calendar import last_session_before, nth_trading_day_after
    stocks = await followed(db, user_id)
    seen = await sent_items(db, user_id)
    nexts = await batch_next_earnings(db, [s["id"] for s in stocks], today) if stocks else {}
    out: list[Section] = []
    tomorrow = nth_trading_day_after(today, 1)
    for s in stocks:
        name = short_name(s["name"], s["symbol"]) or s["symbol"]
        ne = nexts.get(s["id"])
        if ne and ne.date and ne.confirmation == "confirmed":
            timing = await report_timing(db, s["id"], ne.date)
            if "date_confirmed" in kinds and ("date_confirmed", s["symbol"], ne.date.isoformat()) not in seen:
                typical, n = await typical_move(db, s["id"])
                out.append(confirmed_section({"symbol": s["symbol"], "name": name, "date": ne.date, "timing": timing,
                                              "implied": await implied_for_report(db, s["symbol"], ne.date, today),
                                              "report": await report_share(db, s["symbol"], ne.date, today, typical, n), "typical": typical, "n": n}, site))
            if "earnings_eve" in kinds and ne.date == tomorrow and ("earnings_eve", s["symbol"], ne.date.isoformat()) not in seen:
                typical, n = await typical_move(db, s["id"])
                sec = eve_section({"symbol": s["symbol"], "name": name, "date": ne.date, "timing": timing, "read": await read_for(db, s["symbol"]),
                                   "typical": typical, "n": n}, site)
                if sec:
                    out.append(sec)
        if "morning_after" in kinds:
            sec = await after_for(db, user_id, s, name, last_session_before(today), seen, site)
            if sec:
                out.append(sec)
    if "earnings_week" in kinds and today.weekday() == 6 and ("earnings_week", None, (today + timedelta(days=1)).isoformat()) not in seen:
        sec = await week_for(db, stocks, today, site)
        if sec:
            out.append(sec)
    return out


async def read_for(db, symbol: str) -> str | None:
    """Ivy's Read as the ticker page serves it (its stored read for the latest chain), or None."""
    from app.routers.tickers import _stored_options_read
    r = await _stored_options_read(db, symbol)
    return (r or {}).get("content") or None


async def after_for(db, user_id: str, s: dict, name: str, session: date, seen: set, site: str) -> Section | None:
    """The morning-after section when the stock's first session after a report is `session`, the latest stored close."""
    from sqlalchemy import text
    from app.services.trading_calendar import last_session_before
    rows = (await db.execute(text("""SELECT event_date, report_timing::text AS timing FROM events WHERE ticker_id = :t AND event_type = 'earnings'
        AND event_date BETWEEN :a AND :b AND (is_confirmed OR eps_actual IS NOT NULL)"""), {"t": s["id"], "a": last_session_before(session), "b": session})).all()
    for r in rows:
        first, move = await first_session_move(db, s["symbol"], r.event_date, r.timing)
        if first != session or ("morning_after", s["symbol"], session.isoformat()) in seen:
            continue
        hist = []
        for h in (await db.execute(text("""SELECT h.event_date, h.pct_change_1d, e.report_timing::text AS timing FROM historical_reactions h
                LEFT JOIN events e ON e.ticker_id = h.ticker_id AND e.event_type = 'earnings' AND e.event_date = h.event_date
                WHERE h.ticker_id = :t AND h.event_type = 'earnings' AND h.pct_change_1d IS NOT NULL AND h.event_date < :d
                ORDER BY h.event_date DESC LIMIT 12"""), {"t": s["id"], "d": r.event_date})).all():       # past reports: never the one this email is about
            hist.append((float(h.pct_change_1d), await priced_before(db, s["symbol"], h.event_date, h.timing)))
        trades = [{"label": label_of(t), "result": t.result} for t in (await db.execute(text("""SELECT th.result, th.option_type, th.strike, th.strike2, th.option_expiration
            FROM theses th WHERE th.user_id = :u AND th.ticker_id = :t AND th.result IS NOT NULL AND th.option_expiration BETWEEN :a AND :b"""),
            {"u": user_id, "t": s["id"], "a": r.event_date, "b": session})).all()]
        return after_section({"symbol": s["symbol"], "name": name, "session": session, "move": move, "implied": await priced_before(db, s["symbol"], r.event_date, r.timing),
                              "history": hist, "trades": trades}, site)
    return None


def label_of(t) -> str:
    """Pure: "The Dec 18 $200 call", "The Dec 18 $200/$220 call spread"."""
    from app.services.briefing import fmt_date
    strikes = f"${float(t.strike):,.0f}" + (f"/${float(t.strike2):,.0f}" if t.strike2 is not None else "")
    return f"The {fmt_date(t.option_expiration).rsplit(',', 1)[0]} {strikes} {t.option_type}{' spread' if t.strike2 is not None else ''}"


async def week_for(db, stocks: list[dict], today: date, site: str) -> Section | None:
    """Sunday: the company-confirmed reports of the coming Monday to Friday, the largest companies first (by the company's own
    market value, services/market_value; one with no figure comes last, and the vendor's market cap is not read)."""
    from sqlalchemy import text
    from app.services.briefing import short_name
    from app.services.market_value_store import BY_SIZE, SIZE_JOIN
    start, end = today + timedelta(days=1), today + timedelta(days=5)
    rows = (await db.execute(text(f"""SELECT t.symbol, t.name, e.event_date, e.report_timing::text AS timing FROM events e JOIN tickers t ON t.id = e.ticker_id
        {SIZE_JOIN} WHERE t.is_active AND t.index_member AND e.event_type = 'earnings' AND e.is_confirmed AND e.event_date BETWEEN :a AND :b
        ORDER BY {BY_SIZE}"""), {"a": start, "b": end})).all()
    facts = [{"symbol": r.symbol, "name": short_name(r.name, r.symbol) or r.symbol, "date": r.event_date, "timing": r.timing} for r in rows]
    mine = {s["symbol"] for s in stocks}
    return week_section(facts[:WEEK_TOP], [f for f in facts if f["symbol"] in mine], start, end, site)
