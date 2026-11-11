"""Unit tests for command sync in `sidequest.bot.client.SidequestClient._sync_commands`."""

import logging
import unittest.mock

import discord
import pytest

from sidequest.bot.client import SidequestClient
from sidequest.config import Settings
from sidequest.core.clock import SystemClock

DATABASE_URL = "postgresql+asyncpg://u:p@h/db"

SyncCall = tuple[int | None, list[str]]


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
) -> tuple[SidequestClient, list[SyncCall]]:
    """Build a client whose `tree.sync` records each call instead of talking to Discord.

    Each record is (guild id or None for global, command names registered for that scope).
    """
    settings = make_settings(sync_global=sync_global, sync_guild_ids=sync_guild_ids)
    client = SidequestClient(settings, SystemClock())
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
    return client, calls


async def test_global_sync_without_guilds(monkeypatch: pytest.MonkeyPatch) -> None:
    client, calls = make_client(monkeypatch, sync_global=True, sync_guild_ids=[])

    await client.setup_hook()

    assert calls == [(None, ["sidequest"])]


async def test_global_sync_clears_guild_commands_for_listed_guilds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, calls = make_client(monkeypatch, sync_global=True, sync_guild_ids=[1, 2])

    await client.setup_hook()

    assert calls == [(None, ["sidequest"]), (1, []), (2, [])]


async def test_server_only_sync_moves_commands_to_guilds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, calls = make_client(monkeypatch, sync_global=False, sync_guild_ids=[1, 2])

    await client.setup_hook()

    assert calls == [(None, []), (1, ["sidequest"]), (2, ["sidequest"])]


async def test_guild_sync_failure_is_logged_and_skipped(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    client, calls = make_client(
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
