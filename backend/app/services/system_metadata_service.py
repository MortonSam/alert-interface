from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_metadata import SystemMetadata


async def get_value(session: AsyncSession, key: str) -> str | None:
    row = await session.scalar(select(SystemMetadata).where(SystemMetadata.key == key))
    return row.value if row else None


async def set_value(session: AsyncSession, key: str, value: str) -> None:
    stmt = (
        pg_insert(SystemMetadata)
        .values(key=key, value=value, updated_at=datetime.now(timezone.utc))
        .on_conflict_do_update(
            index_elements=["key"],
            set_={"value": value, "updated_at": datetime.now(timezone.utc)},
        )
    )
    await session.execute(stmt)
