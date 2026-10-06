"""Unit tests for v2 close logic: worthless spreads and missing stock close."""
from decimal import Decimal
from types import SimpleNamespace

from app.scripts.close_alert_picks import _compute_stock_move, _find_leg, _leg_mid


# ── _leg_mid ──────────────────────────────────────────────────────────────────

class TestLegMid:
    def test_normal_bid_ask(self):
        """Standard bid/ask returns the midpoint."""
        assert _leg_mid({"bid": 1.0, "ask": 1.20}) == 1.10

    def test_bid_zero_ask_positive(self):
        """Worthless-ish leg: bid=0, ask>0 returns ask/2."""
        assert _leg_mid({"bid": 0, "ask": 0.10}) == 0.05

    def test_both_zero(self):
        """Fully worthless leg: both zero returns 0.0 (not None)."""
        assert _leg_mid({"bid": 0, "ask": 0}) == 0.0

    def test_missing_keys(self):
        """Missing bid/ask keys treated as zero."""
        assert _leg_mid({}) == 0.0

    def test_none_values(self):
        """None bid/ask treated as zero."""
        assert _leg_mid({"bid": None, "ask": None}) == 0.0

    def test_negative_ignored(self):
        """Negative bid/ask treated as zero."""
        assert _leg_mid({"bid": -0.5, "ask": -0.1}) == 0.0


# ── _find_leg ─────────────────────────────────────────────────────────────────

class TestFindLeg:
    def test_found(self):
        side = [{"strike": 100.0, "bid": 1}, {"strike": 105.0, "bid": 2}]
        assert _find_leg(side, 105.0) == {"strike": 105.0, "bid": 2}

    def test_not_found(self):
        side = [{"strike": 100.0, "bid": 1}]
        assert _find_leg(side, 110.0) is None

    def test_empty(self):
        assert _find_leg([], 100.0) is None


# ── Worthless spread closes at -100% ─────────────────────────────────────────

class TestWorthlessSpread:
    """A spread where both legs are bid=0/ask=0 should produce spread_mid=0.0
    and option P&L of -100%."""

    def test_worthless_spread_mid_is_zero(self):
        long_row = {"strike": 100.0, "bid": 0, "ask": 0}
        short_row = {"strike": 105.0, "bid": 0, "ask": 0}
        mid1 = _leg_mid(long_row)
        mid2 = _leg_mid(short_row)
        spread_mid = round(mid1 - mid2, 4)
        assert spread_mid == 0.0

    def test_worthless_spread_pnl(self):
        """Simulates the P&L calculation in _close_v2_picks for a worthless spread."""
        spread_mid = 0.0
        cost = 1.50  # original debit
        pnl_d = round((spread_mid - cost) * 100, 2)
        pnl_p = round((spread_mid - cost) / cost, 4)
        assert pnl_d == -150.0
        assert pnl_p == -1.0  # -100%

    def test_partially_worthless_spread(self):
        """Short leg worthless (bid=0, ask=0.02), long leg has value."""
        long_row = {"strike": 100.0, "bid": 0.80, "ask": 1.00}
        short_row = {"strike": 105.0, "bid": 0, "ask": 0.02}
        mid1 = _leg_mid(long_row)  # 0.90
        mid2 = _leg_mid(short_row)  # 0.01
        spread_mid = round(mid1 - mid2, 4)
        assert spread_mid == 0.89


# ── Missing stock close leaves nulls ─────────────────────────────────────────

class TestMissingStockClose:
    def test_compute_stock_move_valid(self):
        pick = SimpleNamespace(entry_price=Decimal("100.00"))
        result = _compute_stock_move(pick, 105.0)
        assert result == Decimal("5.0000")

    def test_compute_stock_move_null_entry(self):
        pick = SimpleNamespace(entry_price=None)
        assert _compute_stock_move(pick, 105.0) is None

    def test_a_pick_is_never_closed_without_its_close_jbl_exactly(self):
        """JBL, production, 2026-09-30: exit_date Sep 30, the nightly ran at 06:59Z before that session, Yahoo had no
        Sep 30 bar and the chain was Sep 29's. The old closer marked it closed with close_price null on the day-before
        spread mark. Now it waits with the reason, closes the next run on the Sep 30 close and a Sep 30 chain, and
        expiration is a hard stop only with a valid close."""
        from datetime import date
        from app.scripts.close_alert_picks import settle_decision
        exit_date, expiration = date(2026, 9, 30), "2026-10-02"
        # 06:59Z on exit_date: no Sep 30 close yet, chain dated Sep 29
        assert settle_decision(exit_date, expiration, date(2026, 9, 30), 12.4, None, "2026-09-29T20:00:00+00:00", None) == \
            ("wait", "no stock close for 2026-09-30 yet")
        # the next run: the close exists but the chain is still Sep 29's: the exit mark is not there yet
        assert settle_decision(exit_date, expiration, date(2026, 10, 1), 12.4, None, "2026-09-29T20:00:00+00:00", 320.1) == \
            ("wait", "chain dated 2026-09-29, the exit mark needs 2026-09-30 or later")
        # close and a Sep 30 chain: closes
        assert settle_decision(exit_date, expiration, date(2026, 10, 1), 12.4, None, "2026-09-30T20:00:00+00:00", 320.1) == ("close", "")
        assert settle_decision(exit_date, expiration, date(2026, 10, 1), 0.0, None, "2026-10-01", 320.1) == ("close", "")   # worthless spread still closes
        # no chain at all: waits with the store's note, and after expiration becomes the hard stop
        assert settle_decision(exit_date, expiration, date(2026, 10, 1), None, "no chain for 2026-10-02", None, 320.1) == ("wait", "no chain for 2026-10-02")
        assert settle_decision(exit_date, expiration, date(2026, 10, 3), None, "no chain for 2026-10-02", None, 320.1) == ("hard_stop", "no chain for 2026-10-02")
        assert settle_decision(exit_date, expiration, date(2026, 10, 3), 12.4, None, "2026-09-29", None) == ("hard_stop", "no stock close for 2026-09-30 yet")

    def test_the_closer_only_closes_through_the_decision_and_can_reopen_a_pick_closed_without_a_close(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parents[1] / "app" / "scripts" / "close_alert_picks.py").read_text()
        v2 = src[src.index("async def _close_v2_picks"):src.index("async def _reopen_null_close")]
        # every closed status in the v2 path sits under the decision's close branch or a valid expiration close
        assert v2.count('pick.status = "closed"') == 2
        assert 'if action == "close":' in v2 and 'if _is_valid_price(exp_close):' in v2
        assert "stock close unavailable" not in src
        non_v2 = src[src.index("async def _close_picks"):src.index("async def _resolve_close_from_iv_history")]
        assert "if not _is_valid_price(close_price):" in non_v2 and non_v2.index("if not _is_valid_price(close_price):") < non_v2.index('pick.status = "closed"')
        assert '"--reopen-null-close" in sys.argv' in src
        assert 'record_step_fields(STEP_LABEL, {"closed": closed, "waiting": waiting, "auto_voided": auto_voided})' in src
