"""Block 2 (2026-10-20): with PERSONAL_USE_DATA_SHOWN off (the default), nothing that rests on Finnhub's free plan or Yahoo reaches a
visitor: quotes are the stored Intrinio close, company news, analyst data and the Finnhub market cap are withheld, report dates follow
LICENSED_DATES_ONLY, and the Yahoo forward ex-dividend date is left out."""
from types import SimpleNamespace

import pytest

from app.config import Settings, settings
from app.services import personal_use as P


def test_the_flag_defaults_off():
    assert Settings.model_fields["personal_use_data_shown"].default is False


def test_held_data_is_withheld(monkeypatch):
    monkeypatch.setattr(settings, "personal_use_data_shown", False)
    monkeypatch.setattr(settings, "licensed_dates_only", False)
    assert not P.shown() and P.dates_licensed_only()
    assert P.withheld_event(SimpleNamespace(event_type="analyst_action", source="finnhub"))
    assert P.withheld_event(SimpleNamespace(event_type="ex_dividend", source="yfinance"))
    assert not P.withheld_event(SimpleNamespace(event_type="ex_dividend", source="intrinio"))
    assert not P.withheld_event(SimpleNamespace(event_type="earnings", source="finnhub"))       # its date follows LICENSED_DATES_ONLY
    from app.schemas.ticker import TickerRead
    import uuid
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    t = TickerRead(id=uuid.uuid4(), symbol="NVDA", market_cap=5_160_000_000_000, created_at=now, updated_at=now)
    assert t.model_dump()["market_cap"] is None


def test_shown_restores_them(monkeypatch):
    monkeypatch.setattr(settings, "personal_use_data_shown", True)
    monkeypatch.setattr(settings, "licensed_dates_only", False)
    assert P.shown() and not P.dates_licensed_only()
    assert not P.withheld_event(SimpleNamespace(event_type="analyst_action", source="finnhub"))
    from app.schemas.ticker import TickerRead
    import uuid
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    assert TickerRead(id=uuid.uuid4(), symbol="NVDA", market_cap=5, created_at=now, updated_at=now).model_dump()["market_cap"] == 5


@pytest.mark.asyncio
async def test_a_visitor_quote_is_the_stored_intrinio_close_while_held(monkeypatch):
    monkeypatch.setattr(settings, "personal_use_data_shown", False)
    from app.services import quote_fallback
    from app.services.finnhub_client import FinnhubClient
    from app.services.finnhub_limiter import VISITOR

    async def fake_close(symbol):
        return {"c": 217.09, "t": 1, "basis": "close"}

    async def no_request(*a, **k):
        raise AssertionError("Finnhub was asked")

    monkeypatch.setattr(quote_fallback, "stored_close_quote", fake_close)
    client = FinnhubClient(priority=VISITOR)
    monkeypatch.setattr(client, "_request", no_request)
    assert (await client.get_quote("NVDA"))["basis"] == "close"
    await client.close()


@pytest.mark.asyncio
async def test_discover_withholds_analyst_stats_while_held(monkeypatch):
    """The first version put this guard inside _batch_analyst_stats's docstring, where it never ran (found 2026-10-26)."""
    from app.database import ScriptSessionLocal
    from app.routers.discover import _batch_analyst_stats, _batch_buy_share_delta
    monkeypatch.setattr(settings, "personal_use_data_shown", False)

    class NoQuery:
        async def execute(self, *a, **k):
            raise AssertionError("analyst data was read while held")
    assert await _batch_analyst_stats(NoQuery(), ["NVDA"]) == {} and await _batch_buy_share_delta(NoQuery(), ["NVDA"]) == {}
