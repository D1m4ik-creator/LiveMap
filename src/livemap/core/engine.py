from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from livemap.core.config import get_settings

@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.database.get_db_url(),
        echo=settings.database.echo,
        pool_pre_ping=True,
        connect_args={"ssl": True} if settings.database.ssl else {},
    )


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


async def close_engine() -> None:
    get_session_factory.cache_clear()
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
        get_engine.cache_clear()


SessionDep = Annotated[AsyncSession, Depends(get_session)]
