"""Tests for credit shadow pick strike selection and P&L math."""
from decimal import Decimal

import pytest

from app.scripts.auto_pick import _build_iron_condor, _leg_mid


# ── Strike selection ─────────────────────────────────────────────────────────

def _make_chain(put_strikes, call_strikes, bids=None, asks=None):
    """Build a minimal chain_data dict for testing."""
    def _row(strike, side_bids, side_asks, i):
        return {
            "strike": strike,
            "bid": side_bids[i] if side_bids else 1.0,
            "ask": side_asks[i] if side_asks else 1.5,
        }

    puts = [_row(s, bids, asks, i) for i, s in enumerate(put_strikes)]
    calls = [_row(s, bids, asks, i) for i, s in enumerate(call_strikes)]
    return {
        "puts": puts,
        "calls": calls,
        "underlying_price": 100.0,
    }


class TestLegMid:
    def test_normal_bid_ask(self):
        assert _leg_mid({"bid": 2.0, "ask": 4.0}) == 3.0

    def test_bid_zero_ask_positive(self):
        assert _leg_mid({"bid": 0, "ask": 2.0}) == 1.0

    def test_both_zero(self):
        assert _leg_mid({"bid": 0, "ask": 0}) == 0.0

    def test_missing_keys(self):
        assert _leg_mid({}) == 0.0


class TestStrikeSelection:
    """Verify iron condor selects the right strikes relative to expected move."""

    @pytest.mark.asyncio
    async def test_correct_strikes(self):
        """Short strikes should be outside 1.25x expected move, longs one strike beyond."""
        from unittest.mock import AsyncMock, patch

        # spot=100, expected_pct=5 -> put_target=93.75, call_target=106.25
        # Short legs (closer to money) have higher premiums
        puts = [
            {"strike": 88, "bid": 0.10, "ask": 0.20},
            {"strike": 90, "bid": 0.20, "ask": 0.40},
            {"strike": 92, "bid": 0.50, "ask": 0.80},
            {"strike": 94, "bid": 1.00, "ask": 1.50},
            {"strike": 96, "bid": 2.00, "ask": 2.50},
            {"strike": 98, "bid": 3.50, "ask": 4.00},
        ]
        calls = [
            {"strike": 102, "bid": 3.50, "ask": 4.00},
            {"strike": 104, "bid": 2.00, "ask": 2.50},
            {"strike": 106, "bid": 1.00, "ask": 1.50},
            {"strike": 108, "bid": 0.50, "ask": 0.80},
            {"strike": 110, "bid": 0.20, "ask": 0.40},
            {"strike": 112, "bid": 0.10, "ask": 0.20},
        ]
        chain_data = {"puts": puts, "calls": calls, "underlying_price": 100.0}

        with patch("app.scripts.auto_pick.chain_store") as mock_cs:
            mock_cs.pick_expiration = AsyncMock(return_value="2026-10-17")
            mock_cs.get_chain = AsyncMock(return_value=(chain_data, "2026-09-15"))

            session = AsyncMock()
            receipt = {"expected_pct": 5.0, "implied_pct": 8.0}
            from datetime import date
            ic = await _build_iron_condor(session, "TEST", date(2026, 9, 20), receipt)

        assert ic is not None
        # Short put = max strike <= 93.75 -> 92
        assert float(ic.short_put_strike) == 92
        # Long put = next below 92 -> 90
        assert float(ic.long_put_strike) == 90
        # Short call = min strike >= 106.25 -> 108
        assert float(ic.short_call_strike) == 108
        # Long call = next above 108 -> 110
        assert float(ic.long_call_strike) == 110


class TestPnlMath:
    """Verify P&L calculations from credit and close value."""

    def test_profitable_trade(self):
        """Credit > close_value -> positive P&L."""
        credit = 2.50
        close_value = 0.50
        max_loss = 2.50  # 5-wide wing - 2.50 credit

        pnl_dollars = round((credit - close_value) * 100, 2)
        pnl_pct = round(pnl_dollars / (max_loss * 100), 4)

        assert pnl_dollars == 200.0
        assert pnl_pct == 0.8  # 80% return on risk

    def test_losing_trade(self):
        """Credit < close_value -> negative P&L."""
        credit = 1.00
        close_value = 4.00
        max_loss = 4.00

        pnl_dollars = round((credit - close_value) * 100, 2)
        pnl_pct = round(pnl_dollars / (max_loss * 100), 4)

        assert pnl_dollars == -300.0
        assert pnl_pct == -0.75


class TestCreditMustBePositive:
    """Iron condor with inverted structure (credit <= 0) returns None."""

    @pytest.mark.asyncio
    async def test_negative_credit_returns_none(self):
        from unittest.mock import AsyncMock, patch
        from datetime import date

        # Make long legs more expensive than short legs
        puts = [
            {"strike": 90, "bid": 3.0, "ask": 4.0},  # long put (expensive)
            {"strike": 92, "bid": 0.5, "ask": 0.8},   # short put (cheap)
        ]
        calls = [
            {"strike": 108, "bid": 0.5, "ask": 0.8},  # short call (cheap)
            {"strike": 110, "bid": 3.0, "ask": 4.0},   # long call (expensive)
        ]
        chain_data = {"puts": puts, "calls": calls, "underlying_price": 100.0}

        with patch("app.scripts.auto_pick.chain_store") as mock_cs:
            mock_cs.pick_expiration = AsyncMock(return_value="2026-10-17")
            mock_cs.get_chain = AsyncMock(return_value=(chain_data, "2026-09-15"))

            session = AsyncMock()
            receipt = {"expected_pct": 5.0, "implied_pct": 8.0}
            ic = await _build_iron_condor(session, "TEST", date(2026, 9, 20), receipt)

        assert ic is None


class TestMissingLeg:
    """If any leg is missing from the chain, return None."""

    @pytest.mark.asyncio
    async def test_missing_call_wing_returns_none(self):
        from unittest.mock import AsyncMock, patch
        from datetime import date

        # Only one call strike -> no long call available
        puts = [
            {"strike": 90, "bid": 0.5, "ask": 1.0},
            {"strike": 92, "bid": 1.0, "ask": 1.5},
        ]
        calls = [
            {"strike": 108, "bid": 1.0, "ask": 1.5},
            # No strike above 108 for long call
        ]
        chain_data = {"puts": puts, "calls": calls, "underlying_price": 100.0}

        with patch("app.scripts.auto_pick.chain_store") as mock_cs:
            mock_cs.pick_expiration = AsyncMock(return_value="2026-10-17")
            mock_cs.get_chain = AsyncMock(return_value=(chain_data, "2026-09-15"))

            session = AsyncMock()
            receipt = {"expected_pct": 5.0, "implied_pct": 8.0}
            ic = await _build_iron_condor(session, "TEST", date(2026, 9, 20), receipt)

        assert ic is None

    @pytest.mark.asyncio
    async def test_no_expiration_returns_none(self):
        from unittest.mock import AsyncMock, patch
        from datetime import date

        with patch("app.scripts.auto_pick.chain_store") as mock_cs:
            mock_cs.pick_expiration = AsyncMock(return_value=None)

            session = AsyncMock()
            receipt = {"expected_pct": 5.0, "implied_pct": 8.0}
            ic = await _build_iron_condor(session, "TEST", date(2026, 9, 20), receipt)

        assert ic is None

    @pytest.mark.asyncio
    async def test_missing_receipt_fields_returns_none(self):
        from unittest.mock import AsyncMock
        from datetime import date

        session = AsyncMock()
        # Missing implied_pct
        receipt = {"expected_pct": 5.0}
        ic = await _build_iron_condor(session, "TEST", date(2026, 9, 20), receipt)
        assert ic is None
