"""Build a Trade reads a fresh chain whenever one is stored (services/draft_chain): the nightly stores the draft's expiration
outside the 5-chain cap, the draft picks among fresh chains only, one guard (chain_store.is_fresh, the NYSE calendar) serves the
router and validate's draft_path_fresh. The PANW case is production's 2026-10-12 chain."""
import asyncio
from datetime import date
from pathlib import Path

from app.scripts import validate_data as V
from app.services import chain_store, draft_chain
from app.services.chain_shadow import draft_expirations, wanted_expirations
from app.services.draft_chain import (DRAFT_DAYS_AFTER_REPORT, DRAFT_DAYS_WITHOUT_REPORT, draft_min_expiration, options_age_refusal,
                                      pick_draft_chain)

LISTED = ["2026-10-16", "2026-10-23", "2026-10-30", "2026-11-06", "2026-11-13", "2026-11-20", "2026-12-18", "2027-01-15"]


def test_min_expiration_constants():
    assert DRAFT_DAYS_AFTER_REPORT == 14 and DRAFT_DAYS_WITHOUT_REPORT == 7
    assert draft_min_expiration(date(2026, 11, 17), date(2026, 10, 14)) == "2026-12-01"
    assert draft_min_expiration(None, date(2026, 10, 14)) == "2026-10-21"


def test_nightly_keeps_the_drafts_expiration_outside_the_cap():
    """PANW, 2026-10-12: front Oct 16, the report's Nov 13 / Nov 20, courier Oct 23, Oct 30, Dec 18. The cap of 5 dropped Dec 18,
    the expiration a draft reads (first on or after Nov 17 + 14 days)."""
    args = (LISTED, "2026-10-12", ["2026-10-16", "2026-10-23", "2026-10-30", "2026-12-18"], [("2026-11-17", "amc")], 5)
    before = wanted_expirations(*args)
    assert "2026-12-18" not in before and len(before) == 5
    draft = draft_expirations(LISTED, "2026-10-12", ["2026-11-17"])
    assert draft == ["2026-12-18"]
    after = wanted_expirations(*args, draft=draft)
    assert set(after) == set(before) | {"2026-12-18"}       # exempt from the cap: the capped five are unchanged


def test_draft_expirations_follow_the_draft_day():
    # no report: the first expiry at least 7 days after each draft day in the window (Oct 13 to Oct 17)
    assert draft_expirations(LISTED, "2026-10-12", []) == ["2026-10-23", "2026-10-30"]
    # a report inside the window: drafts after it read the next report's expiry
    # (Oct 13-14 drafts follow the Oct 14 report: Oct 30; later drafts follow Jan 20, 2027, and nothing is listed past Feb 3)
    assert draft_expirations(LISTED, "2026-10-12", ["2026-10-14", "2027-01-20"]) == ["2026-10-30"]
    assert draft_expirations(LISTED, "2026-10-12", ["2027-03-01"]) == []        # nothing listed far enough out


def _fake_store(monkeypatch, rows: dict[str, str]):
    async def exps(db, sym, source=None):
        return sorted(rows)

    async def pick(db, sym, min_date, source=None):
        return next((e for e in sorted(rows) if e >= min_date), None)

    async def get(db, sym, exp, source=None):
        return ({"calls": [], "puts": [], "chain_last_trade": rows[exp]}, rows[exp]) if exp in rows else None
    monkeypatch.setattr(chain_store, "get_ingested_expirations", exps)
    monkeypatch.setattr(chain_store, "pick_expiration", pick)
    monkeypatch.setattr(chain_store, "get_chain", get)


def test_draft_picks_the_first_fresh_chain(monkeypatch):
    _fake_store(monkeypatch, {"2026-11-20": "2026-10-12", "2026-12-18": "2026-10-09", "2027-01-15": "2026-10-12"})
    got = asyncio.run(pick_draft_chain(None, "PANW", "2026-12-01", today=date(2026, 10, 14)))
    assert (got.expiration, got.chain_last_trade, got.fresh) == ("2027-01-15", "2026-10-12", True)


def test_no_fresh_chain_refuses_with_the_existing_sentence(monkeypatch):
    _fake_store(monkeypatch, {"2026-12-18": "2026-10-09"})
    got = asyncio.run(pick_draft_chain(None, "PANW", "2026-12-01", today=date(2026, 10, 14)))
    assert (got.expiration, got.fresh) == ("2026-12-18", False)
    assert options_age_refusal("PANW", got.chain_last_trade, date(2026, 10, 14)) == \
        "Ivy won't draft PANW on stale options data (as of 2026-10-09). Options data is updated once a day."
    _fake_store(monkeypatch, {})
    none = asyncio.run(pick_draft_chain(None, "JPM", "2027-01-28", today=date(2026, 10, 14)))
    assert none.chain is None and none.expiration is None


def test_guard_counts_nyse_sessions():
    assert options_age_refusal("X", "2026-10-12", date(2026, 10, 14)) is None
    assert options_age_refusal("X", "2026-10-09", date(2026, 10, 14)) is not None
    # Wed before Thanksgiving to the Monday after: Thu is a holiday, so two sessions (the old weekday loop counted three)
    assert options_age_refusal("X", "2026-11-25", date(2026, 11, 30)) is None
    assert options_age_refusal("X", None, date(2026, 10, 14)) is None


def test_router_uses_the_shared_guard_and_pick():
    src = (Path(__file__).resolve().parents[1] / "app" / "routers" / "thesis.py").read_text()
    assert "pick_draft_chain(db, sym, min_exp)" in src
    assert "options_age_refusal(sym, chain_last_trade)" in src
    assert "d.weekday() < 5" not in src
    assert "timedelta(days=14)).isoformat()" not in src


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _Session:
    """Answers validate's two queries: the active symbols, then (symbol, next report)."""
    def __init__(self, syms, nxt):
        self.answers = [_Result(syms), _Result(nxt)]

    async def execute(self, *_a, **_k):
        return self.answers.pop(0)


def _check(monkeypatch, rows_by_sym, newest, deals=()):
    async def pick(db, sym, min_exp, today=None):
        rows = rows_by_sym.get(sym, {})
        fresh = [e for e in sorted(rows) if e >= min_exp and chain_store.is_fresh(rows[e], today=today)]
        stale = [e for e in sorted(rows) if e >= min_exp]
        e = (fresh or stale or [None])[0]
        return draft_chain.DraftChain(e, {} if e else None, rows.get(e), bool(fresh))

    async def latest(db, sym, source=None):
        return newest.get(sym)

    async def deal(db, sym):
        return object() if sym in deals else None
    import app.services.pending_deals as pd
    monkeypatch.setattr(draft_chain, "pick_draft_chain", pick)
    monkeypatch.setattr(chain_store, "get_latest_chain_date", latest)
    monkeypatch.setattr(pd, "deal_for", deal)
    syms = sorted(set(rows_by_sym) | set(deals))
    return asyncio.run(V.check_draft_path_fresh(_Session(syms, [("PANW", date(2026, 11, 17))]), today=date(2026, 10, 14)))


def test_validate_errors_when_a_fresh_chain_is_refused(monkeypatch):
    r = _check(monkeypatch, {"PANW": {"2026-12-18": "2026-10-09"}, "O": {"2026-11-20": "2026-10-12"}}, {"PANW": "2026-10-12", "O": "2026-10-12"})
    assert r.level == V.ERROR and r.figures["draft_refused_fresh"] == 1
    assert r.rows == ["PANW: picks 2026-12-18 dated 2026-10-09; newest chain 2026-10-12"]


def test_validate_warns_when_nothing_is_stored_far_enough(monkeypatch):
    r = _check(monkeypatch, {"JPM": {}, "O": {"2026-11-20": "2026-10-12"}}, {"O": "2026-10-12"}, deals=("AES",))
    assert r.level == V.WARN and r.rows == ["JPM: no stored expiration on or after 2026-10-21"]


def test_validate_passes_when_every_draft_chain_is_fresh(monkeypatch):
    r = _check(monkeypatch, {"PANW": {"2026-12-18": "2026-10-12"}}, {"PANW": "2026-10-12"})
    assert r.level == V.PASS
    assert V.check_draft_path_fresh in V.CHECKS
