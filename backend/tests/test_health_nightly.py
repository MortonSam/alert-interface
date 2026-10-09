"""/health carries refresh_started_at, the raw start of a run still marked in progress, so the push gate can refuse mid-nightly even
after /health's 45-minute refresh_in_progress rule has stopped reporting the run (scripts/push_window.nightly_block)."""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.main import app

pytestmark = pytest.mark.xdist_group(name="shared_rows")      # writes the shared refresh_in_progress_since key


@pytest.mark.asyncio(loop_scope="session")
async def test_health_reports_the_start_of_a_run_still_marked_in_progress():
    async with ScriptSessionLocal() as s:
        old = (await s.execute(text("SELECT value FROM system_metadata WHERE key = 'refresh_in_progress_since'"))).scalar()
    started = (datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat()
    try:
        async with ScriptSessionLocal() as s:
            await s.execute(text("""INSERT INTO system_metadata (key, value, updated_at) VALUES ('refresh_in_progress_since', :v, now())
                                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"""), {"v": started})
            await s.commit()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            h = (await c.get("/api/v1/health")).json()
        assert h["refresh_started_at"] == started and h["refresh_in_progress"] is False     # 90 minutes: past the 45-minute rule
    finally:
        async with ScriptSessionLocal() as s:
            if old is None:
                await s.execute(text("DELETE FROM system_metadata WHERE key = 'refresh_in_progress_since'"))
            else:
                await s.execute(text("UPDATE system_metadata SET value = :v WHERE key = 'refresh_in_progress_since'"), {"v": old})
            await s.commit()
