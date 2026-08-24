from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from livemap.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database.get_db_url(),
    echo=settings.database.echo,
    pool_pre_ping=True,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def close_engine() -> None:
    await engine.dispose()


SessionDep = Annotated[AsyncSession, Depends(get_session)]
