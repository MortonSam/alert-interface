"""Ivy v3's pricing desk (services/pricing_desk): the typical move, the probability, each structure's expected value on a hand-made
chain, the verdict rule, the bands, the step on one seeded symbol, the endpoints' gates, and the paused picks."""
import json
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.main import app
from app.scripts.validate_data import CHECKS, ERROR, PASS, check_pricing_cards
from app.services import pricing_desk as P
from app.services.ivy_outcomes import IVY_OUTCOMES, REFUSED
from app.services.ivy_v2 import PICKS_PAUSED, PICKS_PAUSED_REASON

pytestmark = pytest.mark.xdist_group(name="pricing_desk")

CHAIN = {90: {"call": {"bid": 11.0, "ask": 11.4}, "put": {"bid": 1.0, "ask": 1.2}}, 95: {"call": {"bid": 6.5, "ask": 6.9}, "put": {"bid": 1.9, "ask": 2.1}},
         100: {"call": {"bid": 3.0, "ask": 3.2}, "put": {"bid": 2.9, "ask": 3.1}}, 105: {"call": {"bid": 1.0, "ask": 1.2}, "put": {"bid": 6.0, "ask": 6.4}},
         110: {"call": {"bid": 0.3, "ask": 0.5}, "put": {"bid": 10.5, "ask": 10.9}}}


def test_typical_move_shrinks_toward_the_sector_and_fills_sit_at_the_real_bid_and_ask():
    sector = [0.05] * 30
    assert P.typical_move([], sector) == pytest.approx(0.05) and P.typical_move([0.10], sector) == pytest.approx(0.05)                 # fewer than MIN_PRIOR: the sector alone
    assert round(P.typical_move([0.10, 0.10], sector), 4) == round((2 * 0.10 + 6 * 0.05) / 8, 4)          # n against SHRINK_K
    assert P.typical_move([0.1] * 5, [0.05] * 10) is None                                                 # too little sector history
    q = {"bid": 3.0, "ask": 3.2}
    assert P.fill(q, "buy", 0.5) == 3.2 and P.fill(q, "sell", 0.5) == 3.0 and P.fill(q, "buy", 1.0) == pytest.approx(3.3) and P.fill({"bid": None, "ask": 3}, "buy", 0.5) is None
    assert P.p_beyond(np.array([0.5, 1.5, -2.0, 0.1] * 60), 0.04, 0.045) == pytest.approx(0.5)            # |z| τ > 4.5%: the 1.5 and -2.0 of each four


def test_the_implied_move_is_the_straddles_time_value_when_the_stock_sits_between_strikes():
    """CMS, Oct 19, 2026 (production): spot $67.37 between the $65 and $70 strikes. The $65 straddle's $4.83 mid read as a 7.16% move
    and p_beyond_implied fell to 0.023, under validate's 0.05 floor; $2.37 of that mid is the $65 call's intrinsic value."""
    cms = {65.0: {"call": {"bid": 2.8, "ask": 4.6}, "put": {"bid": 0.35, "ask": 1.9}}, 70.0: {"call": {"bid": 0.55, "ask": 0.75}, "put": {"bid": 2.1, "ask": 4.7}}}
    atm, im = P.implied_move(cms, 67.37)
    assert atm == 65.0 and im == pytest.approx((3.7 + 1.125 - 2.37) / 67.37) and round(im * 100, 2) == 3.64
    assert P.implied_move({100: {"call": {"bid": 0.0, "ask": 0.1}, "put": {"bid": 9.9, "ask": 10.0}}}, 90.0) is None     # no time value left
    assert P.PRICING_COMPUTATION_VERSION == 3


def test_each_structure_prices_from_the_chain_with_known_numbers():
    assert P.implied_move(CHAIN, 100.0) == (100, pytest.approx(0.061))      # (3.1 + 3.0) / 100
    tau, z = 0.04, np.zeros(300)                                                # a stock that never moves: every long structure loses its cost, the condor keeps its credit
    lc = P.evaluate_structure("long_call", P.structure_legs("long_call", CHAIN, 100.0, 0.061, tau), 100.0, tau, z)
    assert lc["cost_per_contract"] == 320.0 and lc["max_loss_per_contract"] == 320.0 and lc["breakeven_pct"] == 3.2 and lc["ev_per_100"] == -100.0 and lc["p_profit"] == 0.0
    st = P.evaluate_structure("long_straddle", P.structure_legs("long_straddle", CHAIN, 100.0, 0.061, tau), 100.0, tau, z)
    assert st["cost_per_contract"] == 630.0 and st["breakeven_pct"] == 6.3 and st["ev_per_100"] == -100.0
    bs_legs = P.structure_legs("bull_call_spread", CHAIN, 100.0, 0.061, tau)
    assert [(L["side"], L["strike"]) for L in bs_legs] == [("buy", 100), ("sell", 105)]                   # the short call nearest spot × (1 + τ) = 104
    bs = P.evaluate_structure("bull_call_spread", bs_legs, 100.0, tau, z)
    assert bs["cost_per_contract"] == 220.0 and bs["ev_per_100"] == -100.0 and bs["ev_per_100_full_spread"] == -100.0       # the debit is the whole loss either way
    ic_legs = P.structure_legs("iron_condor", CHAIN, 100.0, 0.061, tau)
    assert [(L["side"], L["kind"], L["strike"]) for L in ic_legs] == [("sell", "call", 105), ("sell", "put", 95), ("buy", "call", 110), ("buy", "put", 90)]
    ic = P.evaluate_structure("iron_condor", ic_legs, 100.0, tau, z)
    assert ic["cost_per_contract"] == -120.0 and ic["max_loss_per_contract"] == 380.0                   # credit 1.0 + 1.9 - 1.2 - 0.5 = 1.2; width 5 less the credit
    assert ic["ev_per_100"] == pytest.approx(120 / 380 * 100, abs=0.01) and ic["p_profit"] == 1.0          # no move: the whole credit is kept
    up = np.full(300, 3.0)                                                                                # every report moves +12% (3 τ): the call pays 12 - 3.2
    lc_up = P.evaluate_structure("long_call", P.structure_legs("long_call", CHAIN, 100.0, 0.061, tau), 100.0, tau, up)
    assert lc_up["ev_per_100"] == pytest.approx((12 - 3.2) / 3.2 * 100, abs=0.01) and lc_up["p_profit"] == 1.0


def test_the_verdict_and_the_bands():
    assert P.verdict_for({"long_call": {"ev_per_100_full_spread": -5}, "iron_condor": {"ev_per_100_full_spread": -1}}) == ("no_edge", None)
    assert P.verdict_for({"long_call": {"ev_per_100_full_spread": -5}, "iron_condor": {"ev_per_100_full_spread": 2.5}}, earned=True) == ("possible_edge", "iron_condor")
    assert P.verdict_for({"long_call": {"ev_per_100_full_spread": 0.0}}) == ("no_edge", None)              # clearing zero means above it
    card = {"implied_move_pct": 6.1, "typical_move_pct": 4.0, "p_beyond_implied": 0.3, "structures": {"long_call": {"ev_per_100": -45.4, "ev_per_100_full_spread": -47.0}, "iron_condor": None}}
    assert P.band_problems(card) == []
    bad = {**card, "typical_move_pct": 55.0, "structures": {"long_call": {"ev_per_100": 400.0, "ev_per_100_full_spread": -47.0}}}
    assert P.band_problems(bad) == ["typical_move_pct=55.0 outside [0.5, 40.0]", "long_call.ev_per_100=400.0 outside [-100.0, 300.0]"]
    assert P.PRICING_COMPUTATION_VERSION == 3 and check_pricing_cards in CHECKS
    cleared = {"long_call": {"ev_per_100_full_spread": 4.0}, "iron_condor": {"ev_per_100_full_spread": -3.0}}
    assert P.verdict_for(cleared) == ("no_edge", None) and P.POSSIBLE_EDGE_EARNED is False          # not earned on held-out data: no card says possible edge
    assert P.verdict_for(cleared, earned=True) == ("possible_edge", "long_call")
    assert P.horizon_sessions(date(2026, 10, 9), date(2026, 10, 17)) == 5 and P.horizon_sessions(date(2026, 10, 9), date(2026, 10, 10)) == 1 and P.horizon_sessions(date(2026, 10, 9), date(2027, 1, 15)) == P.MAX_HORIZON


def test_picks_are_paused_with_the_reason_recorded_and_the_outcome_labelled():
    assert PICKS_PAUSED is True and PICKS_PAUSED_REASON == "picks paused: the rule failed its 2024-2026 test"
    assert IVY_OUTCOMES["paused"]["category"] == REFUSED and IVY_OUTCOMES["paused"]["label"].startswith("Paused")
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "app" / "scripts" / "auto_pick.py").read_text()
    assert "dry_run=dry_run or cap_hit or PICKS_PAUSED" in src and '"picks_paused": PICKS_PAUSED_REASON if PICKS_PAUSED else None' in src


@pytest.mark.asyncio
async def test_a_built_card_is_stored_served_behind_the_flag_and_judged_by_validate(monkeypatch):
    """One seeded symbol with a chain quoted on five strikes and a sector's worth of history: the card builds, the endpoints gate it, validate reads it."""
    from app.config import settings
    from app.services.pricing_desk import Odds, build_card, card_key, dumps
    from app.services.system_metadata_service import set_value
    sym = "ZZPRC"
    today = date(2026, 10, 12)
    # a sector whose reports sometimes gap past the implied move; over five sessions (the card's horizon) the moves run wider than on the day
    reactions = [{"symbol": f"ZZS{i % 10}", "sector": "Test Sector", "event_date": date(2021, 1, 1) + timedelta(days=7 * i), "pct_change_1d": (2.0, -3.0, 7.5, -9.0, 1.0)[i % 5],
                  "moves": {h: (0.025, -0.04, 0.09, -0.11, 0.015)[i % 5] * (1 + 0.1 * (h - 1)) for h in range(2, P.MAX_HORIZON + 1)}} for i in range(400)]
    reactions += [{"symbol": sym, "sector": "Test Sector", "event_date": date(2026, 1, 15), "pct_change_1d": 5.0}, {"symbol": sym, "sector": "Test Sector", "event_date": date(2026, 4, 15), "pct_change_1d": -6.0}]
    odds = Odds(reactions)
    chain = {"calls": [{"strike": k, "bid": v["call"]["bid"], "ask": v["call"]["ask"]} for k, v in CHAIN.items()], "puts": [{"strike": k, "bid": v["put"]["bid"], "ask": v["put"]["ask"]} for k, v in CHAIN.items()], "chain_source": "intrinio"}
    card = build_card(symbol=sym, report_date=date(2026, 10, 15), report_confirmation="confirmed", chain=chain, chain_date="2026-10-09", chain_source="intrinio",
                      expiration="2026-10-17", spot=100.0, odds=odds, today=today, computed_at=datetime.now(timezone.utc))
    assert isinstance(card, dict), card
    assert card["implied_move_pct"] == 6.1 and card["prior_n"] == 2 and len(card["prior_moves"]) == 2 and set(card["structures"]) == set(P.STRUCTURES)
    assert card["horizon_sessions"] == 5 and card["computation_version"] == 3 and card["pooled_move_to_expiry_pct"] > card["typical_move_pct"]   # the wider distribution
    assert isinstance(P.build_card(symbol=sym, report_date=date(2026, 10, 15), report_confirmation="confirmed", chain=chain, chain_date="2026-10-09", chain_source="intrinio",
                                   expiration="2026-10-17", spot=100.0, odds=P.Odds([{**r, "moves": {}} for r in reactions]), today=today), str)   # no horizon pool: no card, never the 1-day pool
    assert card["verdict"] in ("no_edge", "possible_edge") and card["typical_move_pct"] == pytest.approx(round((2 * 5.5 + 6 * 4.5) / 8, 2), abs=0.05)   # own 5.5% over 2 reports against the sector's 4.5%
    async with ScriptSessionLocal() as s:
        try:
            await set_value(s, card_key(sym), dumps(card)); await s.commit()
            monkeypatch.setattr(settings, "ivy_desk_v3_enabled", False)
            monkeypatch.setattr(settings, "admin_token", "preview-token-for-this-test")
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                assert (await c.get(f"/api/v1/tickers/{sym}/pricing-card")).json() is None                              # off: nothing for a visitor
                assert sym not in [x["symbol"] for x in (await c.get("/api/v1/ivy/desk-v3")).json()]
                h = {"X-Admin-Token": "preview-token-for-this-test"}
                got = (await c.get(f"/api/v1/tickers/{sym}/pricing-card", headers=h)).json()                               # preview sees it
                assert got["symbol"] == sym and got["structures"]["iron_condor"]["legs"][0]["side"] == "sell"
                monkeypatch.setattr(settings, "ivy_desk_v3_enabled", True)
                assert (await c.get(f"/api/v1/tickers/{sym}/pricing-card")).json()["verdict"] == card["verdict"]
                assert (await c.get("/api/v1/ivy/verdicts")).status_code == 200                                             # the ledger gate answers (empty or rows), never errors
            assert P.band_problems(card) == [], P.band_problems(card)                                                      # the seeded card is inside every band
            r = await check_pricing_cards(s)
            assert r.level in (PASS, "warn") or not any(x.startswith(sym + ":") for x in r.rows), (r.level, r.rows[:3])
        finally:
            await s.execute(text("DELETE FROM system_metadata WHERE key = :k"), {"k": card_key(sym)}); await s.commit()


def test_settlement_closes_each_leg_at_the_post_report_quotes_or_intrinsic():
    from app.scripts.pricing_desk import post_session, settle_structure
    assert post_session(date(2026, 10, 15), "bmo") == date(2026, 10, 15) and post_session(date(2026, 10, 15), "amc") == date(2026, 10, 16) and post_session(date(2026, 10, 16), None) == date(2026, 10, 19)
    entry = {"legs": [{"kind": "call", "side": "buy", "strike": 100.0}], "cost_per_contract": 320.0, "max_loss_per_contract": 320.0}
    assert settle_structure("long_call", entry, {100.0: {"call": {"bid": 8.0, "ask": 8.4}}}, 108.0) == pytest.approx((800 - 320) / 320 * 100)   # sold at the bid
    assert settle_structure("long_call", entry, None, 108.0) == pytest.approx((800 - 320) / 320 * 100)                                       # no quote: intrinsic at the close
    assert settle_structure("long_call", entry, None, None) is None


@pytest.mark.asyncio
async def test_a_card_whose_report_has_passed_is_judged_on_its_bands_not_its_version():
    """Version 3 shipped on Oct 20, 2026: the 19 cards of the Oct 19-20 reports are kept for settlement and never rebuilt, so their
    version 2 is not an error; an upcoming report's card on an old version still is."""
    import json as _json
    from datetime import timedelta as _td
    past = {"report_date": (date.today() - _td(days=1)).isoformat(), "computation_version": 2, "implied_move_pct": 6.1, "typical_move_pct": 4.0,
            "p_beyond_implied": 0.3, "structures": {}}
    upcoming = {**past, "report_date": (date.today() + _td(days=2)).isoformat()}

    class _Rows:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

    class _S:
        async def execute(self, *_a, **_k):
            return _Rows([("pricing_card:ZZOLD", _json.dumps(past)), ("pricing_card:ZZNEW", _json.dumps(upcoming))])

    r = await check_pricing_cards(_S())
    assert r.level == ERROR and r.rows == ["ZZNEW: computed by version 2, current is 3"]


def test_a_card_or_verdict_for_a_report_date_that_moved_is_dropped_not_settled():
    """2026-10-21: validate failed on CB's and VMRK's Oct 21 cards (version 2). CB's date became Oct 20 and VMRK's Nov 4 after they
    were priced, so neither was a candidate again; their unsettled verdicts (and OMC's, PNR's, VRT's, ITW's) would have been settled
    against sessions that were not their reports."""
    from app.scripts.pricing_desk import orphans
    d = date.fromisoformat
    cards = [("pricing_card:CB", "CB", d("2026-10-21")), ("pricing_card:VMRK", "VMRK", d("2026-10-21")), ("pricing_card:NFLX", "NFLX", d("2026-10-20"))]
    verdicts = [(1, "CB", d("2026-10-21")), (2, "VMRK", d("2026-10-21")), (3, "NFLX", d("2026-10-20")), (4, "ZZNONE", d("2026-10-22"))]
    reports = {"CB": {d("2026-10-20"), d("2027-02-01")}, "VMRK": {d("2026-11-04")}, "NFLX": {d("2026-10-20")}}
    assert orphans(cards, verdicts, reports) == (["pricing_card:CB", "pricing_card:VMRK"], [1, 2, 4])
    import inspect
    from app.scripts import pricing_desk as PD
    src = inspect.getsource(PD.main)
    assert src.index("await drop_orphans(s)") < src.index("await settle(s, today)")          # never settled first
