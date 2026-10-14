"""The intraday chart asks Intrinio for bars through the session itself: the vendor's end_date is exclusive (start = end returns
no bars, checked against the API on 2026-10-13), so the request ends the day after the session."""
import asyncio
from datetime import date

from app.services import live_data


class _FakeIntrinio:
    """Answers like Intrinio's /prices/intervals: bars on days from start_date up to, not including, end_date."""
    calls: list[dict] = []
    BARS = {"2026-10-12": ["2026-10-12T15:55:00.000-04:00"], "2026-10-13": ["2026-10-13T09:30:00.000-04:00", "2026-10-13T15:55:00.000-04:00"]}

    async def _get(self, path, params):
        _FakeIntrinio.calls.append(params)
        days = [d for d in self.BARS if params["start_date"] <= d < params["end_date"]]
        return {"source": "cboe_one", "intervals": [{"time": t, "close": 100.0} for d in days for t in self.BARS[d]]}

    async def close(self):
        pass


def _run(monkeypatch, **kw):
    import app.services.intrinio_client as ic
    monkeypatch.setattr(ic, "IntrinioClient", _FakeIntrinio)
    live_data._chart_cache.clear()
    _FakeIntrinio.calls = []
    return asyncio.run(live_data.intraday_chart("TSLA", date(2026, 10, 13), 378.03, **kw))


def test_same_day_request_returns_that_days_bars(monkeypatch):
    out = _run(monkeypatch)
    assert [p["date"] for p in out["history"]] == ["2026-10-13T09:30:00.000-04:00", "2026-10-13T15:55:00.000-04:00"]
    assert _FakeIntrinio.calls[0]["start_date"] == "2026-10-13" and _FakeIntrinio.calls[0]["end_date"] == "2026-10-14"
    assert out["start_price"] == 378.03


def test_week_request_includes_the_latest_session(monkeypatch):
    out = _run(monkeypatch, start=date(2026, 10, 4), interval=live_data.WEEK_INTERVAL)
    assert out["history"][-1]["date"].startswith("2026-10-13")
