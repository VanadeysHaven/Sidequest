"""Unit tests for command sync in `sidequest.bot.client.SidequestClient._sync_commands`."""

import logging
import re
import unittest.mock

import discord
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from sidequest.bot.adapter import BotDeps
from sidequest.bot.client import SidequestClient, command_hash
from sidequest.config import Settings
from sidequest.core.clock import SystemClock
from sidequest.scheduler.signal import ScheduleSignal
from sidequest.services.uow import UowFactory

DATABASE_URL = "postgresql+asyncpg://u:p@h/db"
TOP_LEVEL_NAMES = ["settings", "sidequest", "todo"]

SyncCall = tuple[int | None, list[str]]


class MemoryHashStore:
    def __init__(self, value: str | None = None) -> None:
        self.value = value

    async def load(self) -> str | None:
        return self.value

    async def save(self, value: str) -> None:
        self.value = value


def make_deps(command_hashes: MemoryHashStore) -> BotDeps:
    clock = SystemClock()
    return BotDeps(
        uows=UowFactory(async_sessionmaker(), clock),
        signal=ScheduleSignal(),
        command_hashes=command_hashes,
        run_scheduler=False,
    )


def make_settings(*, sync_global: bool, sync_guild_ids: list[int]) -> Settings:
    return Settings(
        _env_file=None,
        discord_token="token",
        database_url=DATABASE_URL,
        sync_global=sync_global,
        sync_guild_ids=sync_guild_ids,
    )


def make_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    sync_global: bool,
    sync_guild_ids: list[int],
    failing_guild_id: int | None = None,
    stored_hash: str | None = None,
) -> tuple[SidequestClient, list[SyncCall], MemoryHashStore]:
    """Build a client whose `tree.sync` records each call instead of talking to Discord.

    Each record is (guild id or None for global, command names registered for that scope).
    """
    settings = make_settings(sync_global=sync_global, sync_guild_ids=sync_guild_ids)
    store = MemoryHashStore(stored_hash)
    client = SidequestClient(settings, SystemClock(), make_deps(store))
    calls: list[SyncCall] = []

    async def fake_sync(*, guild: discord.abc.Snowflake | None = None) -> list[object]:
        names = sorted(c.name for c in client.tree.get_commands(guild=guild))
        calls.append((guild.id if guild is not None else None, names))
        if guild is not None and guild.id == failing_guild_id:
            raise discord.HTTPException(
                unittest.mock.Mock(status=403, reason="Forbidden"), "Missing Access"
            )
        return []

    monkeypatch.setattr(client.tree, "sync", fake_sync)
    return client, calls, store


async def test_global_sync_without_guilds(monkeypatch: pytest.MonkeyPatch) -> None:
    client, calls, _ = make_client(monkeypatch, sync_global=True, sync_guild_ids=[])

    await client.setup_hook()

    assert calls == [(None, TOP_LEVEL_NAMES)]


async def test_global_sync_clears_guild_commands_for_listed_guilds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, calls, _ = make_client(monkeypatch, sync_global=True, sync_guild_ids=[1, 2])

    await client.setup_hook()

    assert calls == [(None, TOP_LEVEL_NAMES), (1, []), (2, [])]


async def test_server_only_sync_moves_commands_to_guilds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, calls, _ = make_client(monkeypatch, sync_global=False, sync_guild_ids=[1, 2])

    await client.setup_hook()

    assert calls == [(None, []), (1, TOP_LEVEL_NAMES), (2, TOP_LEVEL_NAMES)]


async def test_guild_sync_failure_is_logged_and_skipped(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    client, calls, _ = make_client(
        monkeypatch, sync_global=False, sync_guild_ids=[1, 2], failing_guild_id=1
    )
    caplog.set_level(logging.WARNING)

    await client.setup_hook()

    assert [guild_id for guild_id, _ in calls] == [None, 1, 2]
    warnings = [
        record
        for record in caplog.records
        if record.levelno == logging.WARNING
        and record.name == "sidequest.bot.client"
        and "Could not sync commands for guild 1" in record.getMessage()
    ]
    assert len(warnings) == 1


async def test_global_sync_skipped_when_hash_unchanged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    first, _, first_store = make_client(monkeypatch, sync_global=True, sync_guild_ids=[])
    await first.setup_hook()
    stored = first_store.value

    second, calls, _ = make_client(
        monkeypatch, sync_global=True, sync_guild_ids=[1, 2], stored_hash=stored
    )
    caplog.set_level(logging.INFO)

    await second.setup_hook()

    assert None not in [guild_id for guild_id, _ in calls]
    assert [guild_id for guild_id, _ in calls] == [1, 2]
    assert any("Global commands unchanged" in record.getMessage() for record in caplog.records)


async def test_global_sync_runs_when_hash_differs(monkeypatch: pytest.MonkeyPatch) -> None:
    client, calls, store = make_client(
        monkeypatch, sync_global=True, sync_guild_ids=[], stored_hash="old"
    )

    await client.setup_hook()

    assert calls == [(None, TOP_LEVEL_NAMES)]
    assert store.value != "old"
    assert store.value is not None
    assert len(store.value) == 64
    assert re.fullmatch(r"[0-9a-f]{64}", store.value)


async def test_server_only_skips_global_sync_when_hash_matches_empty_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, calls, _ = make_client(
        monkeypatch,
        sync_global=False,
        sync_guild_ids=[1, 2],
        stored_hash=command_hash([]),
    )

    await client.setup_hook()

    assert [guild_id for guild_id, _ in calls] == [1, 2]
    assert all(names == TOP_LEVEL_NAMES for _, names in calls)


async def test_global_sync_runs_when_hash_load_fails(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    client, calls, store = make_client(monkeypatch, sync_global=True, sync_guild_ids=[])

    async def broken_load() -> str | None:
        raise RuntimeError("boom")

    monkeypatch.setattr(store, "load", broken_load)
    caplog.set_level(logging.WARNING)

    await client.setup_hook()

    assert calls == [(None, TOP_LEVEL_NAMES)]
    assert any(
        record.levelno == logging.WARNING
        and "Could not read the command hash: boom" in record.getMessage()
        for record in caplog.records
    )


def test_command_hash_ignores_dict_key_order() -> None:
    assert command_hash([{"a": 1, "b": 2}]) == command_hash([{"b": 2, "a": 1}])
