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
