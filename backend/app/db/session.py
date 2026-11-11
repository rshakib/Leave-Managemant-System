from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.db.urls import connect_args_for

engine = create_async_engine(
    settings.async_database_url,
    echo=False,
    pool_pre_ping=True,
    connect_args=connect_args_for(
        settings.async_database_url, force=settings.db_statement_cache_disabled
    ),
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
