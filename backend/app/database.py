from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

# API engine — tight timeouts for user-facing requests
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_timeout=10,
    connect_args={"server_settings": {"statement_timeout": "15000"}},
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

# Script engine — generous statement timeout for batch processing
script_engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    connect_args={"server_settings": {"statement_timeout": "120000"}},
)
ScriptSessionLocal = async_sessionmaker(script_engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
