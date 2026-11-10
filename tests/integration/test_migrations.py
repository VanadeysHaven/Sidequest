"""Alembic upgrade/downgrade round trip.

These tests are synchronous on purpose: Alembic's env.py runs its own event loop via asyncio.run.
"""

import asyncio

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from sidequest.db.migrate import alembic_config


def _scalar(url: str, sql: str) -> object:
    async def run() -> object:
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                return (await conn.execute(text(sql))).scalar()
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_upgrade_downgrade_upgrade(migrated_database: str) -> None:
    cfg = alembic_config(migrated_database)

    command.downgrade(cfg, "base")
    assert _scalar(migrated_database, "SELECT to_regclass('public.todos')::text") is None

    command.upgrade(cfg, "head")
    assert _scalar(migrated_database, "SELECT to_regclass('public.todos')::text") == "todos"
    head = ScriptDirectory.from_config(cfg).get_current_head()
    assert _scalar(migrated_database, "SELECT version_num FROM alembic_version") == head
