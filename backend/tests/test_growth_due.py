"""compute_growth --due (2026-10-21: the nightly step hit its 3600-second limit with nothing written, every night): due only with a
growth filing since the ticker's last run, each ticker written as it finishes, and a time budget so the step ends inside ten minutes."""
import inspect
from datetime import datetime, timezone

from app.scripts import compute_growth as C


def _sub(*rows):
    return {"filings": {"recent": {"form": [r[0] for r in rows], "items": [r[1] for r in rows], "acceptanceDateTime": [r[2] for r in rows]}}}


def test_the_newest_growth_filing_is_a_periodic_report_or_a_results_8k():
    sub = _sub(("8-K", "5.02", "2026-10-20T16:00:00.000Z"), ("10-Q", "", "2026-10-15T12:00:00.000Z"), ("8-K", "2.02,9.01", "2026-10-14T20:05:00.000Z"),
               ("4", "", "2026-10-21T10:00:00.000Z"))
    assert C.newest_filing(sub) == datetime(2026, 10, 15, 12, tzinfo=timezone.utc)          # a director change or a Form 4 is not one
    assert C.newest_filing(_sub(("8-K", "2.02", "2026-10-21T21:00:00.000Z"))) == datetime(2026, 10, 21, 21, tzinfo=timezone.utc)
    assert C.newest_filing({}) is None


def test_due_means_a_growth_filing_since_the_last_run_newest_first_then_never_run():
    at = lambda d, h=0: datetime(2026, 10, d, h, tzinfo=timezone.utc)
    runs = {"AAA": at(20), "BBB": at(20), "CCC": at(20), "NEW1": None, "NEW0": None}
    newest = {"AAA": at(21, 21), "BBB": at(19), "CCC": at(21, 1)}
    assert C.due_order(runs, newest) == ["AAA", "CCC", "NEW0", "NEW1"]                       # BBB filed nothing since its run


def test_each_ticker_is_written_and_recorded_as_it_finishes_and_the_run_has_a_budget():
    src = inspect.getsource(C.run)
    assert "await write_symbol(sym, *got)" in src                                              # as each ticker finishes
    assert "time.time() - t0 > RUN_BUDGET_S" in src and C.RUN_BUDGET_S <= 8 * 60               # no new ticker after the budget
    assert "asyncio.wait_for(process(sym), max(5.0, RUN_HARD_S" in src and C.RUN_HARD_S < 10 * 60   # a long one stops before ten minutes
    assert "growth_run:" in C.RUN_KEY and "set_value(s, RUN_KEY" in inspect.getsource(C.write_symbol)


def test_requests_made_at_once_still_go_out_one_per_interval():
    import asyncio
    import time
    from app.services import edgar_client as E

    class Client:
        def __init__(self):
            self.at = []

        async def get(self, url, **kw):
            self.at.append(time.monotonic())
            return type("R", (), {"status_code": 200})()
    c, e = Client(), E.EdgarClient.__new__(E.EdgarClient)

    async def burst():
        await asyncio.gather(*(e._paced_get(c, f"/x{i}") for i in range(6)))
    asyncio.run(burst())
    gaps = [b - a for a, b in zip(c.at, c.at[1:])]
    assert min(gaps) >= E.MIN_INTERVAL_S * 0.9, gaps
