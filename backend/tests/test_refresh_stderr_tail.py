"""A failed step's traceback keeps its last lines, where the exception is named, and /health shows them."""
import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.scripts import refresh

TRACEBACK = """Traceback (most recent call last):
  File "/app/app/scripts/auto_pick.py", line 300, in <module>
    sys.exit(asyncio.run(main()))
  File "/usr/local/lib/python3.12/asyncio/runners.py", line 195, in run
    return runner.run(main)
  File "/usr/local/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py", line 563, in _prepare_and_execute
    self._handle_exception(error)
sqlalchemy.exc.ProgrammingError: (sqlalchemy.dialects.postgresql.asyncpg.ProgrammingError) <class 'asyncpg.exceptions.UndefinedColumnError'>: column "x" does not exist
"""


def test_excerpt_keeps_the_head_and_the_exception_line():
    head, tail = refresh._stderr_excerpt(TRACEBACK)
    assert head.splitlines()[0] == "Traceback (most recent call last):"
    assert len(head.splitlines()) == 3
    assert tail.splitlines()[-1].startswith("sqlalchemy.exc.ProgrammingError") and "UndefinedColumnError" in tail
    assert len(tail.splitlines()) == 3
    assert refresh._stderr_excerpt("one\n\ntwo\n") == ("one\ntwo", None)     # short: the head holds it all
    assert refresh._stderr_excerpt("") == (None, None) and refresh._stderr_excerpt(None) == (None, None)


def test_outcome_stores_the_tail_and_a_clean_run_clears_it(monkeypatch):
    store: dict[str, str] = {"step_outcomes": json.dumps({"Auto-pick": {"exit": 0, "seconds": 1.0, "at": "t", "custom": 7}})}
    monkeypatch.setattr(refresh, "_db_get", lambda key: store.get(key))
    monkeypatch.setattr(refresh, "_db_upsert", lambda key, value: store.__setitem__(key, value))
    head, tail = refresh._stderr_excerpt(TRACEBACK)
    refresh._record_step_outcome("Auto-pick", exit_code=1, seconds=12.3, stderr_head=head, stderr_tail=tail)
    entry = json.loads(store["step_outcomes"])["Auto-pick"]
    assert entry["exit"] == 1 and entry["custom"] == 7                   # merged, not replaced
    assert entry["stderr_head"] == head and entry["stderr_tail"] == tail
    refresh._record_step_outcome("Auto-pick", exit_code=0, seconds=2.0)
    entry = json.loads(store["step_outcomes"])["Auto-pick"]
    assert "stderr_tail" not in entry                                     # the next clean run does not keep an old tail


@pytest.mark.asyncio
async def test_health_exposes_the_tail(monkeypatch):
    import app.main as main_module
    outcomes = {"Auto-pick": {"exit": 1, "seconds": 12.3, "at": "t", "stderr_head": "Traceback", "stderr_tail": "X: boom"}}

    async def fake_get_value(session, key):
        return json.dumps(outcomes) if key == "step_outcomes" else None
    monkeypatch.setattr(main_module, "get_value", fake_get_value)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = (await client.get("/health")).json()
    assert body["step_outcomes"]["Auto-pick"]["stderr_tail"] == "X: boom"
