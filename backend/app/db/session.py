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
    # A cloud database drops idle connections; pre_ping checks one before use, so
    # the first request after a quiet spell does not fail.
    pool_pre_ping=True,
    # Empty for a direct/session-pooler URL, statement_cache_size=0 for the
    # transaction pooler (see app/db/urls.py).
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
    """FastAPI dependency that yields a database session per request."""
    async with async_session_factory() as session:
        yield session
