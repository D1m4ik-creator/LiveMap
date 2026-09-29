from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from livemap.core.config import get_settings
from livemap.db.base import Base
import livemap.db.models  # noqa: F401 - register all tables


target_metadata = Base.metadata


def include_name(name: str | None, type_: str, _parent_names: dict) -> bool:
    if type_ == "table":
        return name in target_metadata.tables
    return True


def run_migrations_offline() -> None:
    database = get_settings().migration_database
    url = database.get_db_url().render_as_string(hide_password=False)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        include_name=include_name,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        version_table_schema=database.schema_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_name=include_name,
        compare_type=True,
        version_table_schema=get_settings().database_schema,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    database = get_settings().migration_database
    engine = create_async_engine(database.get_db_url(), poolclass=pool.NullPool,
                                 connect_args=database.get_connect_args())
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
