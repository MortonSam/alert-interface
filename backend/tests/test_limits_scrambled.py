"""The limits keep a scrambled form of a visitor's network address and delete it a day after its last use (Sam, 2026-11-03,
privacy policy question 2)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services import draft_limiter as L

pytestmark = pytest.mark.xdist_group(name="limits_scrambled")


def test_the_address_is_never_the_key():
    key = L._ip_key(L.DRAFT_POLICY, "203.0.113.7")
    assert "203.0.113.7" not in key and key.startswith("draft_rate:ip:") and len(key.split(":")[-1]) == 32
    assert L._ip_key(L.DRAFT_POLICY, "203.0.113.7") == key != L._ip_key(L.DRAFT_POLICY, "203.0.113.8")


@pytest.mark.asyncio
async def test_a_record_unused_for_a_day_is_deleted():
    now = datetime.now(timezone.utc)
    old, fresh = "draft_rate:ip:zz-old-test", "draft_rate:ip:zz-fresh-test"
    async with ScriptSessionLocal() as s:
        try:
            await s.execute(text("INSERT INTO system_metadata (key, value, updated_at) VALUES (:a, '[]', :t1), (:b, '[]', :t2)"),
                            {"a": old, "t1": now - timedelta(hours=25), "b": fresh, "t2": now - timedelta(hours=2)})
            await s.commit()
            assert await L.delete_stale_ip_records(s, now) >= 1
            await s.commit()
            keys = set((await s.execute(text("SELECT key FROM system_metadata WHERE key IN (:a, :b)"), {"a": old, "b": fresh})).scalars())
            assert keys == {fresh}
        finally:
            await s.execute(text("DELETE FROM system_metadata WHERE key IN (:a, :b)"), {"a": old, "b": fresh})
            await s.commit()
