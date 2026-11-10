"""Alembic environment (async, asyncpg)."""

import asyncio
import logging

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from sidequest.config import DatabaseSettings
from sidequest.db.base import Base

config = context.config

# `sidequest migrate` has already configured logging; the bare `alembic` CLI has not.
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(name)s: %(message)s")

target_metadata = Base.metadata


def _database_url() -> str:
    url = config.attributes.get("database_url")
    if url:
        return url
    return DatabaseSettings().database_url  # type: ignore[call-arg]  # from env / .env


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_database_url(), poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
