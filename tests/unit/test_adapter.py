"""Unit tests for sidequest.bot.adapter (Discord glue; fakes only, no network)."""

import unittest.mock
from types import SimpleNamespace

import discord
import pytest

from sidequest.bot import adapter
from sidequest.bot.adapter import ScopeOption
from sidequest.core.enums import Scope
from sidequest.core.errors import InvalidOperation
from sidequest.services.actor import Actor
from sidequest.services.effects import DeleteMessage


def actor(guild_id: int | None) -> Actor:
    return Actor(user_id=1, guild_id=guild_id, can_manage_guild=False, origin="discord")


# --- resolve_scope -----------------------------------------------------------------------


def test_resolve_scope_defaults_to_server_inside_a_guild() -> None:
    assert adapter.resolve_scope(actor(5), None) == Scope.SERVER


def test_resolve_scope_defaults_to_personal_outside_a_guild() -> None:
    assert adapter.resolve_scope(actor(None), None) == Scope.PERSONAL


def test_resolve_scope_server_outside_a_guild_is_an_error() -> None:
    with pytest.raises(InvalidOperation) as info:
        adapter.resolve_scope(actor(None), ScopeOption.Server)
    assert info.value.message == adapter.NOT_IN_SERVER


def test_resolve_scope_personal_inside_a_guild() -> None:
    assert adapter.resolve_scope(actor(5), ScopeOption.Personal) == Scope.PERSONAL


# --- parse_id ----------------------------------------------------------------------------


def test_parse_id_reads_digits() -> None:
    assert adapter.parse_id("42") == 42


def test_parse_id_strips_whitespace() -> None:
    assert adapter.parse_id(" 7 ") == 7


def test_parse_id_free_text_asks_to_pick_from_list() -> None:
    with pytest.raises(InvalidOperation) as info:
        adapter.parse_id("milk")
    assert info.value.message == adapter.PICK_FROM_LIST


def test_parse_id_custom_message() -> None:
    with pytest.raises(InvalidOperation) as info:
        adapter.parse_id("x", "custom")
    assert info.value.message == "custom"


# --- with_notes --------------------------------------------------------------------------


def test_with_notes_joins_notes_and_content() -> None:
    assert adapter.with_notes(["a"], "b") == "a\nb"


def test_with_notes_nothing_at_all_is_none() -> None:
    assert adapter.with_notes([], None) is None


def test_with_notes_only_notes() -> None:
    assert adapter.with_notes(["a"], None) == "a"


# --- user_ids ----------------------------------------------------------------------------


def test_user_ids_skips_missing_users() -> None:
    assert adapter.user_ids([None, SimpleNamespace(id=1), None]) == [1]


def test_user_ids_none_when_no_users_given() -> None:
    assert adapter.user_ids([None, None]) is None


# --- actor_from --------------------------------------------------------------------------


def _interaction(*, guild_integration: bool, permissions: discord.Permissions) -> SimpleNamespace:
    return SimpleNamespace(
        guild_id=5,
        user=SimpleNamespace(id=7),
        permissions=permissions,
        is_guild_integration=lambda: guild_integration,
    )


def test_actor_from_guild_install_with_manage_guild() -> None:
    fake = _interaction(guild_integration=True, permissions=discord.Permissions(manage_guild=True))
    result = adapter.actor_from(fake)  # type: ignore[arg-type]
    assert result.guild_id == 5
    assert result.can_manage_guild is True
    assert result.user_id == 7
    assert result.origin == "discord"


def test_actor_from_user_install_has_no_guild() -> None:
    fake = _interaction(guild_integration=False, permissions=discord.Permissions(manage_guild=True))
    result = adapter.actor_from(fake)  # type: ignore[arg-type]
    assert result.guild_id is None
    assert result.can_manage_guild is False


def test_actor_from_administrator_can_manage_guild() -> None:
    fake = _interaction(guild_integration=True, permissions=discord.Permissions(administrator=True))
    assert adapter.actor_from(fake).can_manage_guild is True  # type: ignore[arg-type]


def test_actor_from_no_permissions_cannot_manage_guild() -> None:
    fake = _interaction(guild_integration=True, permissions=discord.Permissions.none())
    assert adapter.actor_from(fake).can_manage_guild is False  # type: ignore[arg-type]


# --- run_effects -------------------------------------------------------------------------


class FakeMessage:
    def __init__(
        self, recorded: list[tuple[int, int]], channel_id: int, message_id: int, error: Exception
    ) -> None:
        self._recorded = recorded
        self._channel_id = channel_id
        self._message_id = message_id
        self._error = error

    async def delete(self) -> None:
        if self._error is not None:
            raise self._error
        self._recorded.append((self._channel_id, self._message_id))


class FakeChannel:
    def __init__(self, recorded: list[tuple[int, int]], channel_id: int, errors: dict) -> None:
        self._recorded = recorded
        self._channel_id = channel_id
        self._errors = errors

    def get_partial_message(self, message_id: int) -> FakeMessage:
        error = self._errors.get((self._channel_id, message_id))
        return FakeMessage(self._recorded, self._channel_id, message_id, error)


class FakeClient:
    def __init__(self, errors: dict | None = None) -> None:
        self.recorded: list[tuple[int, int]] = []
        self._errors = errors or {}

    def get_partial_messageable(self, channel_id: int) -> FakeChannel:
        return FakeChannel(self.recorded, channel_id, self._errors)


async def test_run_effects_deletes_each_message() -> None:
    client = FakeClient()
    effects = [DeleteMessage(channel_id=1, message_id=2), DeleteMessage(channel_id=3, message_id=4)]

    await adapter.run_effects(client, effects)  # type: ignore[arg-type]

    assert client.recorded == [(1, 2), (3, 4)]


async def test_run_effects_not_found_is_ignored_and_next_effect_runs() -> None:
    not_found = discord.NotFound(
        unittest.mock.Mock(status=404, reason="Not Found"), "Unknown Message"
    )
    client = FakeClient(errors={(1, 2): not_found})
    effects = [DeleteMessage(channel_id=1, message_id=2), DeleteMessage(channel_id=3, message_id=4)]

    await adapter.run_effects(client, effects)  # type: ignore[arg-type]

    assert client.recorded == [(3, 4)]


async def test_run_effects_forbidden_is_ignored_and_next_effect_runs() -> None:
    forbidden = discord.Forbidden(unittest.mock.Mock(status=403, reason="Forbidden"), "x")
    client = FakeClient(errors={(1, 2): forbidden})
    effects = [DeleteMessage(channel_id=1, message_id=2), DeleteMessage(channel_id=3, message_id=4)]

    await adapter.run_effects(client, effects)  # type: ignore[arg-type]

    assert client.recorded == [(3, 4)]
