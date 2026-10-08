"""Shared test setup: one event loop for every database-backed test.

pytest.ini gives async tests a session-scoped loop. Sync tests that need the
database are written as async tests for that reason; tests that only exercise
pure code may still call asyncio.run on a private loop, since they never touch
the shared engine pools. The fixture below closes the pools on that same loop
when the session ends, so no connection outlives its loop.
"""
import pytest
import pytest_asyncio

from app.database import engine, script_engine


@pytest_asyncio.fixture(scope="session", autouse=True, loop_scope="session")
async def _dispose_engines_on_the_session_loop():
    yield
    await engine.dispose()
    await script_engine.dispose()


@pytest.hookimpl(tryfirst=True)      # before xdist's own hook, which writes the group into each node id
def pytest_collection_modifyitems(items):
    """Under pytest-xdist (`-n auto --dist loadgroup`, the push gate), a file's tests stay on one worker: most files create and delete a
    symbol of their own in each test, and two of those tests on two workers delete each other's rows (test_public_research_generation's
    ZZGEN, 2026-10-08). A file that shares rows with other files sets its own `pytestmark = pytest.mark.xdist_group(...)`, which wins."""
    for item in items:
        if item.get_closest_marker("xdist_group") is None:
            item.add_marker(pytest.mark.xdist_group(name=item.module.__name__))
