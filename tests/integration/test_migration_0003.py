"""Migration 0003 (server lists): data steps on a 0002 database (S8 §3.3).

Synchronous like test_migrations.py: Alembic's env.py runs its own event loop.
"""

import asyncio
from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from sidequest.db.migrate import alembic_config

GUILD_A = 111
GUILD_B = 222  # has to-dos but no guild_settings row


def _run(url: str, sql: str, params: dict[str, Any] | None = None) -> Sequence[Row[Any]]:
    async def run() -> Sequence[Row[Any]]:
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(sql), params or {})
                return result.all() if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _insert_todo(url: str, scope: str, guild_id: int | None, title: str, **extra: Any) -> int:
    row = _run(
        url,
        "INSERT INTO todos (scope, guild_id, owner_id, title, kind, timezone, status, created_at) "
        "VALUES (:scope, :guild_id, 5, :title, 'once', 'UTC', :status, :created_at) RETURNING id",
        {
            "scope": scope,
            "guild_id": guild_id,
            "title": title,
            "status": extra.get("status", "open"),
            "created_at": datetime.fromisoformat(extra.get("created_at", "2030-01-01T00:00:00Z")),
        },
    )
    return int(row[0][0])


@pytest.fixture
def at_0002(migrated_database: str) -> Iterator[str]:
    """The test database downgraded to 0002; back at head and emptied afterwards."""
    cfg = alembic_config(migrated_database)
    command.downgrade(cfg, "0002")
    try:
        yield migrated_database
    finally:
        command.upgrade(cfg, "head")
        _run(
            migrated_database,
            "TRUNCATE todos, todo_lists, user_settings, guild_settings, user_guild_settings "
            "RESTART IDENTITY CASCADE",
        )


def test_upgrade_moves_server_todos_onto_default_lists(at_0002: str) -> None:
    url = at_0002
    _run(
        url,
        "INSERT INTO guild_settings (guild_id, reminder_channel_id) VALUES (:g, 10)",
        {"g": GUILD_A},
    )
    _run(url, "INSERT INTO user_settings (user_id, dm_failed_at) VALUES (5, now())")

    personal = _insert_todo(url, "personal", None, "Mine")
    _run(
        url,
        "INSERT INTO subtasks (todo_id, position, title) VALUES (:t, 0, 'step')",
        {"t": personal},
    )
    _run(url, "INSERT INTO occurrences (todo_id, due_at) VALUES (:t, now())", {"t": personal})

    first = _insert_todo(url, "server", GUILD_A, "Bins", created_at="2030-01-01T00:00:00Z")
    second = _insert_todo(url, "server", GUILD_A, "bins", created_at="2030-01-02T00:00:00Z")
    done = _insert_todo(
        url, "server", GUILD_A, "Bins", status="done", created_at="2029-12-31T00:00:00Z"
    )
    other = _insert_todo(url, "server", GUILD_B, "Groceries")

    command.upgrade(alembic_config(url), "0003")

    # Personal rows and their children are gone.
    assert _run(url, "SELECT id FROM todos WHERE id = :t", {"t": personal}) == []
    assert _run(url, "SELECT count(*) FROM subtasks")[0][0] == 0
    assert _run(url, "SELECT count(*) FROM occurrences")[0][0] == 0

    # One ownerless "Default List" per guild, set as the guild's fallback list.
    lists = _run(url, "SELECT id, guild_id, name, owner_id FROM todo_lists ORDER BY guild_id")
    assert [(r.guild_id, r.name, r.owner_id) for r in lists] == [
        (GUILD_A, "Default List", None),
        (GUILD_B, "Default List", None),
    ]
    list_of = {r.guild_id: r.id for r in lists}
    defaults = _run(url, "SELECT guild_id, default_list_id FROM guild_settings ORDER BY guild_id")
    assert [(r.guild_id, r.default_list_id) for r in defaults] == [
        (GUILD_A, list_of[GUILD_A]),
        (GUILD_B, list_of[GUILD_B]),
    ]

    # Every to-do points at its guild's list; the open duplicate was renamed.
    todos = {r.id: r for r in _run(url, "SELECT id, guild_id, list_id, title FROM todos")}
    assert set(todos) == {first, second, done, other}
    for row in todos.values():
        assert row.list_id == list_of[row.guild_id]
    assert todos[first].title == "Bins"
    assert todos[second].title == "bins (2)"
    assert todos[done].title == "Bins"
    assert todos[other].title == "Groceries"

    # DM bookkeeping is gone.
    columns = _run(
        url,
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'user_settings' AND column_name = 'dm_failed_at'",
    )
    assert columns == []


def test_dedupe_skips_taken_suffixes_and_keeps_titles_within_limit(at_0002: str) -> None:
    url = at_0002
    long_title = "x" * 200
    a = _insert_todo(url, "server", GUILD_A, "Bins", created_at="2030-01-01T00:00:00Z")
    b = _insert_todo(url, "server", GUILD_A, "Bins (2)", created_at="2030-01-02T00:00:00Z")
    c = _insert_todo(url, "server", GUILD_A, "BINS", created_at="2030-01-03T00:00:00Z")
    d = _insert_todo(url, "server", GUILD_A, long_title, created_at="2030-01-04T00:00:00Z")
    e = _insert_todo(url, "server", GUILD_A, long_title, created_at="2030-01-05T00:00:00Z")

    command.upgrade(alembic_config(url), "0003")

    titles = {r.id: r.title for r in _run(url, "SELECT id, title FROM todos")}
    assert titles[a] == "Bins"
    assert titles[b] == "Bins (2)"
    assert titles[c] == "BINS (3)"
    assert titles[d] == long_title
    assert titles[e] == "x" * 196 + " (2)"
    assert len(titles[e]) == 200
