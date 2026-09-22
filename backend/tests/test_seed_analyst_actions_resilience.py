"""The analyst-actions step survives a slow provider: per-ticker timeout, 404 skipped, progress checkpointed."""
import asyncio
import time
from types import SimpleNamespace

import pytest

import app.scripts.seed_analyst_actions as m


def _ticker(sym: str):
    return SimpleNamespace(symbol=sym, id=sym)


def test_a_hung_fetch_costs_one_timeout_and_one_retry_not_161_seconds(monkeypatch):
    monkeypatch.setattr(m, "FETCH_TIMEOUT", 0.05)
    monkeypatch.setattr(m, "RETRY_DELAYS", (0.01,))
    monkeypatch.setattr(m, "_fetch_analyst_actions_sync", lambda sym: time.sleep(5))
    async def go():
        t0 = time.monotonic()
        out = await m._process_ticker(_ticker("HUNG"), asyncio.get_event_loop())
        return out, time.monotonic() - t0
    (outcome, inserted, detail), took = asyncio.run(go())
    assert outcome == "failed" and detail == "timeout" and inserted == 0
    assert took < 2      # the caller gets control back after one timeout and one retry, not 3 x 45 s + 26 s


def test_a_404_or_empty_result_is_done_not_retried(monkeypatch):
    calls = []
    def empty(sym):
        calls.append(sym)
        return []            # yfinance returns an empty frame on a 404
    monkeypatch.setattr(m, "_fetch_analyst_actions_sync", empty)
    async def go():
        return await m._process_ticker(_ticker("ERIE"), asyncio.get_event_loop())
    outcome, _, _ = asyncio.run(go())
    assert outcome == "empty" and calls == ["ERIE"]


def test_progress_is_checkpointed_after_every_batch_and_the_budget_stops_cleanly(monkeypatch):
    saved: list[dict] = []
    async def fake_save(data): saved.append(dict(data))
    async def fake_load(): return {}
    monkeypatch.setattr(m, "_save_attempted", fake_save)
    monkeypatch.setattr(m, "_load_attempted", fake_load)
    monkeypatch.setattr(m, "BATCH_SIZE", 2)
    monkeypatch.setattr(m, "BATCH_SLEEP", 0)
    monkeypatch.setattr(m, "TIME_BUDGET_SECONDS", 0)      # budget exhausted once the first batch has run
    async def fake_process(t, loop): return ("ok", 1, None)
    monkeypatch.setattr(m, "_process_ticker", fake_process)

    # Run just the batch loop by calling main() with a stubbed candidate query.
    class _Result:
        def __init__(self, rows): self._rows = rows
        def scalars(self): return self
        def all(self): return self._rows
    class _Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def execute(self, q): return _Result([_ticker("A"), _ticker("B"), _ticker("C"), _ticker("D")])
    monkeypatch.setattr(m, "AsyncSessionLocal", lambda: _Session())

    rc = asyncio.run(m.main())
    assert rc == 0                                         # partial progress is success, not a failed step
    assert len(saved) == 1 and set(saved[0]) == {"A", "B"}  # first batch checkpointed before the budget stop


def test_failed_tickers_are_marked_attempted_so_the_rotation_moves_on(monkeypatch):
    saved: list[dict] = []
    async def fake_save(data): saved.append(dict(data))
    async def fake_load(): return {}
    monkeypatch.setattr(m, "_save_attempted", fake_save)
    monkeypatch.setattr(m, "_load_attempted", fake_load)
    monkeypatch.setattr(m, "BATCH_SIZE", 5)
    monkeypatch.setattr(m, "BATCH_SLEEP", 0)
    async def fake_process(t, loop): return ("failed", 0, "timeout") if t.symbol == "X" else ("ok", 2, None)
    monkeypatch.setattr(m, "_process_ticker", fake_process)
    class _Result:
        def __init__(self, rows): self._rows = rows
        def scalars(self): return self
        def all(self): return self._rows
    class _Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def execute(self, q): return _Result([_ticker("X"), _ticker("Y")])
    monkeypatch.setattr(m, "AsyncSessionLocal", lambda: _Session())
    assert asyncio.run(m.main()) == 0
    assert set(saved[-1]) == {"X", "Y"}
