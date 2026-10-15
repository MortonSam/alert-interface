"""The report-only expected move (services/report_move): the pair E = sqrt(T2 x (s2^2 - s1^2)) when it qualifies, else the term
method from the first two expirations after the report, the move 0.80 x E; the options do not separate a report move only when
neither gives a positive E; the ticker page's verdict and Discover's line state the same figure and sentence; held facts drop both."""
import math
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services import report_move as RM
from app.services.iv_solver import bs_price
from app.services.move_comparison import MIN_REPORTS, REPORT_MOVE_ABSENT, report_sentence, report_verdict

pytestmark = pytest.mark.xdist_group(name="report_move")


def test_worked_example():
    # s1 30% to Oct 23, s2 60% to Oct 30, chain Oct 14: T2 = 16/365, s2^2 - s1^2 = 0.36 - 0.09 = 0.27
    t2 = 16 / 365
    e = math.sqrt(t2 * 0.27)                        # 0.108790...
    assert abs(e - 0.10879) < 1e-5
    assert abs(RM.report_move_pct(0.30, 0.60, t2) - 0.80 * e) < 1e-12
    assert round(RM.report_move_pct(0.30, 0.60, t2) * 100, 1) == 8.7
    assert RM.REPORT_SHARE == 0.80


def test_no_report_move_when_the_later_expiration_is_not_priced_higher():
    assert RM.report_move_pct(0.40, 0.40, 0.05) is None
    assert RM.report_move_pct(0.45, 0.40, 0.05) is None
    assert RM.report_move_pct(0.30, 0.60, 0.0) is None


def test_term_worked_example():
    # s2 60% to Oct 30 (T2 16/365), s3 45% to Nov 20 (T3 37/365), chain Oct 14
    t2, t3 = 16 / 365, 37 / 365
    base = (0.45 ** 2 * t3 - 0.60 ** 2 * t2) / (t3 - t2)          # 0.0825, a normal volatility of about 28.7%
    assert abs(base - 0.0825) < 1e-12 and abs(RM.term_base(0.60, t2, 0.45, t3) - base) < 1e-12
    e = math.sqrt(t2 * (0.36 - base))                               # 0.110293...
    assert abs(RM.term_move_pct(0.60, t2, 0.45, t3) - 0.80 * e) < 1e-12
    assert round(RM.term_move_pct(0.60, t2, 0.45, t3) * 100, 1) == 8.8


def test_term_gives_no_move_without_a_positive_variance():
    t2, t3 = 16 / 365, 37 / 365
    assert RM.term_move_pct(0.40, t2, 0.50, t3) is None            # the later expiration priced higher: base above s2^2
    assert RM.term_move_pct(0.90, t2, 0.30, t3) is None            # base below zero is not a variance
    assert RM.term_move_pct(0.60, t2, 0.45, t2) is None            # T3 not after T2


def test_legs_around_the_report():
    exps = ["2026-10-16", "2026-10-23", "2026-10-30", "2026-11-20"]
    # an after-close report on Oct 23: the Oct 23 expiry is before it, Oct 30 captures it, Nov 20 is the next after
    assert RM.pick_legs(exps, "2026-10-23", "amc", "2026-10-14") == ("2026-10-23", "2026-10-30", "2026-11-20")
    # before the open, the report-day expiry captures it
    assert RM.pick_legs(exps, "2026-10-23", "bmo", "2026-10-14") == ("2026-10-16", "2026-10-23", "2026-10-30")
    # nothing stored between the chain date and the report: no expiration before it
    assert RM.pick_legs(["2026-10-30", "2026-11-20"], "2026-10-23", "amc", "2026-10-14") == (None, "2026-10-30", "2026-11-20")
    # an expiry on or before the chain date is not a leg
    assert RM.pick_legs(["2026-10-14", "2026-10-30"], "2026-10-23", None, "2026-10-14") == (None, "2026-10-30", None)


def test_the_pair_qualifies_only_five_sessions_out_and_within_21_days_of_the_report():
    # chain Wed Oct 14: the fifth session after it is Wed Oct 21
    assert RM.pair_qualifies("2026-10-21", "2026-10-30", "2026-10-23", "2026-10-14")
    assert not RM.pair_qualifies("2026-10-20", "2026-10-30", "2026-10-23", "2026-10-14")      # four sessions out
    assert not RM.pair_qualifies("2026-10-16", "2026-11-20", "2026-10-19", "2026-10-14")      # the dev failure: days against weeks
    assert RM.pair_qualifies("2026-10-23", "2026-11-13", "2026-10-23", "2026-10-14")          # 21 days after the report
    assert not RM.pair_qualifies("2026-10-23", "2026-11-14", "2026-10-23", "2026-10-14")      # 22
    assert not RM.pair_qualifies(None, "2026-10-30", "2026-10-23", "2026-10-14")


def _chain(spot: float, k: float, sigma: float, chain_day: date, exp: str, rate: float) -> dict:
    t = (date.fromisoformat(exp) - chain_day).days / 365
    c, p = bs_price("call", spot, k, t, rate, sigma), bs_price("put", spot, k, t, rate, sigma)
    return {"underlying_price": spot, "chain_last_trade": chain_day.isoformat(),
            "calls": [{"strike": k, "bid": c - 0.005, "ask": c + 0.005}], "puts": [{"strike": k, "bid": p - 0.005, "ask": p + 0.005}]}


def _patch_store(monkeypatch, chains: dict[str, dict], post: str | None, timing="amc", rate=0.04):
    from app.services import chain_store, rates
    async def pick(db, sym, min_date, source=None): return post
    async def get(db, sym, exp, source=None): return (chains[exp], chains[exp]["chain_last_trade"]) if exp in chains else None
    async def exps(db, sym, source=None): return sorted(chains)
    async def timing_on(db, sym, day): return timing
    async def rate_on(db, on, series=None): return rates.RateOn(rate, on, None)
    monkeypatch.setattr(chain_store, "pick_expiration", pick)
    monkeypatch.setattr(chain_store, "get_chain", get)
    monkeypatch.setattr(chain_store, "get_ingested_expirations", exps)
    monkeypatch.setattr(chain_store, "report_timing_on", timing_on)
    monkeypatch.setattr(chain_store, "is_fresh", lambda clt, max_trading_days=2, today=None: True)
    monkeypatch.setattr(rates, "rate_on", rate_on)


@pytest.mark.asyncio
async def test_report_move_solves_both_legs_and_carries_its_receipts(monkeypatch):
    cd = date(2026, 10, 14)
    chains = {"2026-10-23": _chain(100.0, 100.0, 0.30, cd, "2026-10-23", 0.04), "2026-10-30": _chain(100.0, 100.0, 0.60, cd, "2026-10-30", 0.04)}
    _patch_store(monkeypatch, chains, "2026-10-30")
    rm = await RM.report_move(None, "ZZRM", "2026-10-23", cd)
    assert rm.state == RM.OK
    assert abs(rm.before.atm_iv - 0.30) < 2e-3 and abs(rm.after.atm_iv - 0.60) < 2e-3
    assert (rm.before.expiration, rm.after.expiration, rm.before.chain_date, rm.after.chain_date) == ("2026-10-23", "2026-10-30", "2026-10-14", "2026-10-14")
    assert abs(rm.t2_years - 16 / 365) < 1e-12
    assert abs(rm.pct - RM.report_move_pct(rm.before.atm_iv, rm.after.atm_iv, 16 / 365)) < 1e-12 and round(rm.pct * 100, 1) == 8.7
    assert rm.method == RM.PAIR and rm.version == 2
    assert set(rm.as_dict()) >= {"state", "pct", "e", "t2_years", "before", "after", "report_date", "version", "method", "later"}


@pytest.mark.asyncio
async def test_a_pair_that_does_not_qualify_gives_way_to_the_term_method(monkeypatch):
    cd = date(2026, 10, 14)
    # report Oct 19 after the close: the pre leg (Oct 16) is two sessions away, the post leg (Nov 20) a month out
    chains = {e: _chain(100.0, 100.0, iv, cd, e, 0.04) for e, iv in (("2026-10-16", 0.30), ("2026-11-20", 0.60), ("2026-12-18", 0.50))}
    _patch_store(monkeypatch, chains, "2026-11-20")
    rm = await RM.report_move(None, "ZZRM", "2026-10-19", cd)
    assert rm.state == RM.OK and rm.method == RM.TERM and rm.before is None
    assert (rm.after.expiration, rm.later.expiration) == ("2026-11-20", "2026-12-18")
    want = RM.term_move_pct(rm.after.atm_iv, rm.t2_years, rm.later.atm_iv, rm.t3_years)
    assert abs(rm.pct - want) < 1e-12 and rm.base_variance > 0


@pytest.mark.asyncio
async def test_a_qualifying_pair_with_no_positive_e_falls_to_the_term_method(monkeypatch):
    cd = date(2026, 10, 14)
    chains = {e: _chain(100.0, 100.0, iv, cd, e, 0.04) for e, iv in (("2026-10-23", 0.62), ("2026-10-30", 0.60), ("2026-11-20", 0.45))}
    _patch_store(monkeypatch, chains, "2026-10-30")
    rm = await RM.report_move(None, "ZZRM", "2026-10-23", cd)
    assert rm.state == RM.OK and rm.method == RM.TERM and rm.before.atm_iv > rm.after.atm_iv


@pytest.mark.asyncio
async def test_edge_cases_say_the_options_do_not_separate_a_report_move(monkeypatch):
    cd = date(2026, 10, 14)
    # no expiration before the report and none after the first post-report one: no method has its legs
    _patch_store(monkeypatch, {"2026-10-30": _chain(100.0, 100.0, 0.60, cd, "2026-10-30", 0.04)}, "2026-10-30")
    rm = await RM.report_move(None, "ZZRM", "2026-10-23", cd)
    assert rm.state == RM.NO_LEGS and rm.pct is None
    # the pair alone, s2 not above s1
    chains = {"2026-10-23": _chain(100.0, 100.0, 0.50, cd, "2026-10-23", 0.04), "2026-10-30": _chain(100.0, 100.0, 0.45, cd, "2026-10-30", 0.04)}
    _patch_store(monkeypatch, chains, "2026-10-30")
    rm = await RM.report_move(None, "ZZRM", "2026-10-23", cd)
    assert rm.state == RM.NOT_SEPARATED and rm.pct is None and rm.before.atm_iv > rm.after.atm_iv
    # both methods computed, neither positive
    chains["2026-11-20"] = _chain(100.0, 100.0, 0.65, cd, "2026-11-20", 0.04)
    _patch_store(monkeypatch, chains, "2026-10-30")
    rm = await RM.report_move(None, "ZZRM", "2026-10-23", cd)
    assert rm.state == RM.NOT_SEPARATED and rm.pct is None and rm.later.expiration == "2026-11-20"
    assert REPORT_MOVE_ABSENT[RM.NOT_SEPARATED].startswith("The options don't separate a report move")
    assert not any(s.startswith("The options don't separate") for k, s in REPORT_MOVE_ABSENT.items() if k != RM.NOT_SEPARATED)
    # every state other than ok has a sentence, and visible wording carries no colon
    assert set(REPORT_MOVE_ABSENT) == set(RM.STATES) - {RM.OK}
    assert not any(":" in s or "—" in s or "stored" in s for s in REPORT_MOVE_ABSENT.values())


def test_verdict_speaks_only_past_the_ratios_and_over_enough_reports():
    assert report_verdict(6.0, 4.0, MIN_REPORTS) == "more than usual"
    assert report_verdict(4.8, 4.0, MIN_REPORTS) == "about its usual"
    assert report_verdict(3.1, 4.0, MIN_REPORTS) == "less than usual"
    assert report_verdict(6.0, 4.0, MIN_REPORTS - 1) is None and report_verdict(None, 4.0, 20) is None
    assert report_sentence(8.7, 4.0, "more than usual", date(2026, 10, 14)) == \
        "Options price a move of about 8.7% from the report itself, more than the 4.0% it has moved on a typical report (options from Oct 14, 2026)."


SYM = "ZZRM"


async def _seed(held_fact: str | None = None):
    async with ScriptSessionLocal() as s:
        await _clean(s)
        await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active) VALUES (gen_random_uuid(), :s, 'Report move test', true)"), {"s": SYM})
        await s.execute(text("""INSERT INTO events (id, ticker_id, event_type, event_date, title, source, is_confirmed, metadata, created_at)
                                SELECT gen_random_uuid(), id, 'earnings', :d, 'ZZRM earnings', 'manual', true, '{}'::jsonb, now() FROM tickers WHERE symbol = :s"""),
                        {"s": SYM, "d": date.today() + timedelta(days=9)})
        if held_fact:
            await s.execute(text("INSERT INTO fact_holds (symbol, fact, check_name, detail, since) VALUES (:s, :f, 'test_check', 'ZZRM test', now())"), {"s": SYM, "f": held_fact})
        await s.commit()


async def _clean(s):
    await s.execute(text("DELETE FROM fact_holds WHERE symbol = :s"), {"s": SYM})
    await s.execute(text("DELETE FROM events WHERE ticker_id IN (SELECT id FROM tickers WHERE symbol = :s)"), {"s": SYM})
    await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": SYM})


def _patch_move(monkeypatch, typical=4.0, n=20):
    fixed = RM.ReportMove(RM.OK, pct=0.087, e=0.087 / 0.8, t2_years=16 / 365,
                          before=RM.Leg("2026-10-23", "2026-10-14", 100.0, 0.30), after=RM.Leg("2026-10-30", "2026-10-14", 100.0, 0.60), report_date="x")
    async def fake(db, sym, report_date, today=None): return fixed
    async def cond(db, symbols): return {s: {"total": n, "avg_abs_1d": typical} for s in symbols}
    import app.routers.discover as D
    monkeypatch.setattr(RM, "report_move", fake)
    monkeypatch.setattr(D, "_batch_conditional_stats", cond)


@pytest.mark.asyncio
async def test_the_ticker_verdict_and_discover_state_the_same_figure_and_sentence(monkeypatch):
    from app.routers.discover import _batch_move_comparison, _batch_conditional_stats
    from app.routers.tickers import _report_move_fields
    _patch_move(monkeypatch)
    try:
        await _seed()
        today = date.today()
        row = SimpleNamespace(symbol=SYM, event_date=today + timedelta(days=9), is_confirmed=True, unresolved_since=None)
        async with ScriptSessionLocal() as db:
            import app.routers.discover as D
            disc = (await _batch_move_comparison(db, [row], await D._batch_conditional_stats(db, [SYM]), today))[SYM]
            page = await _report_move_fields(db, SYM, today, [])
        assert page["comparison"] == disc["comparison"] == \
            "Options price a move of about 8.7% from the report itself, more than the 4.0% it has moved on a typical report (options from Oct 14, 2026)."
        assert round(page["report_move_pct"] * 100, 1) == disc["report_move_pct"] == 8.7
        assert page["move_comparison"] == disc["move_comparison"] == "more than usual"
        assert page["report_move"] == disc["report_move"] and page["held"] is False
    finally:
        async with ScriptSessionLocal() as s:
            await _clean(s)
            await s.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("fact", ["implied_move", "typical_move"])
async def test_a_held_fact_drops_the_comparison_and_says_held(monkeypatch, fact):
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    from app.routers.tickers import _report_move_fields
    _patch_move(monkeypatch)
    try:
        await _seed(fact)
        async with ScriptSessionLocal() as db:
            from app.services.fact_holds import holds_for
            page = await _report_move_fields(db, SYM, date.today(), sorted(await holds_for(db, SYM)))
        assert page["held"] is True and fact in page["held_facts"]
        assert page.get("move_comparison") is None
        if fact == "implied_move":
            assert page.get("report_move_pct") is None and page.get("comparison") is None
        else:                                         # the report move stands on its own, with no typical move beside it
            assert page["typical_move_pct"] is None and "typical" not in page["comparison"]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            body = (await c.get(f"/api/v1/reactions/summary?symbol={SYM}")).json()
        assert body["held"] is (fact == "typical_move") and fact in body["held_facts"]
    finally:
        async with ScriptSessionLocal() as s:
            await _clean(s)
            await s.commit()


@pytest.mark.asyncio
async def test_the_strip_the_overview_and_ask_ivy_state_discovers_sentence(monkeypatch):
    """Every surface states the report move in the same words: Discover's line, the ticker verdict, the strip question, the
    Overview clause and Ask Ivy's facts (services/report_move.report_move_view)."""
    from app.routers.discover import _batch_move_comparison
    from app.routers.tickers import _report_move_fields
    from app.services import ask_ivy as A
    from app.services import briefing_build as BB
    from app.services.next_earnings import NextEarnings
    _patch_move(monkeypatch)
    today = date.today()
    async def fake_next(db, ticker_id, when):
        return NextEarnings(date=today + timedelta(days=9), source="edgar", confirmation="confirmed", note="x")
    monkeypatch.setattr(BB, "next_earnings_for", fake_next)
    try:
        await _seed()
        row = SimpleNamespace(symbol=SYM, event_date=today + timedelta(days=9), is_confirmed=True, unresolved_since=None)
        async with ScriptSessionLocal() as db:
            import app.routers.discover as D
            disc = (await _batch_move_comparison(db, [row], await D._batch_conditional_stats(db, [SYM]), today))[SYM]["comparison"]
            page = (await _report_move_fields(db, SYM, today, []))["comparison"]
            qs = await BB.build_questions(db, SYM, today, all_candidates=True)
            brief = await BB.build_briefing(db, SYM, today)
            pack = await A.fact_pack(db, SYM, today)
        assert disc == page == "Options price a move of about 8.7% from the report itself, more than the 4.0% it has moved on a typical report (options from Oct 14, 2026)."
        strip = next((q for q in qs["questions"] if q["key"] == "implied_big"), None)
        assert strip is not None and strip["data"] == disc, [q["key"] for q in qs["questions"]]
        assert any(s["text"].endswith(disc) for s in brief["sentences"]), [s["text"] for s in brief["sentences"]]
        facts = {f["id"]: f for f in pack["facts"]}
        assert facts["report_move_sentence"]["value"] == disc and facts["implied_vs_typical"]["value"] == "more than usual"
        assert "implied_move_by_first_expiration_after_report" not in facts            # no straddle figure beside the report move
    finally:
        async with ScriptSessionLocal() as s:
            await _clean(s)
            await s.commit()


@pytest.mark.asyncio
async def test_the_options_bundle_the_page_reads_carries_the_same_report_move(monkeypatch):
    """The ticker page reads /tickers/options-bundle, not /tickers/expected-move: both return the report move and its sentence."""
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    _patch_move(monkeypatch)
    try:
        await _seed()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            em = (await c.get(f"/api/v1/tickers/expected-move/{SYM}")).json()
            bundle = (await c.get(f"/api/v1/tickers/options-bundle/{SYM}")).json()["expected_move"]
        assert em["comparison"].startswith("Options price a move of about 8.7% from the report itself")
        for k in ("report_move_state", "report_move", "comparison", "move_comparison", "typical_move_pct", "typical_n", "held"):
            assert bundle[k] == em[k], k
    finally:
        async with ScriptSessionLocal() as s:
            await _clean(s)
            await s.commit()
