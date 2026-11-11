"""Glue between Discord interactions and the services (S5 adapter rules).

Command pattern::

    await defer(interaction)
    actor = actor_from(interaction)
    async with uows(interaction)() as uow:
        out = await todos.complete(uow, actor, todo_id)
        notes = await collect_notes(uow, actor.user_id)
    todo = await apply(interaction, out)
    await reply(interaction, render.something(todo), notes=notes)
"""

import enum
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol, cast

import discord
from sqlalchemy.ext.asyncio import AsyncEngine

from sidequest.core.discord_time import ts
from sidequest.core.enums import Scope
from sidequest.core.errors import InvalidOperation
from sidequest.core.timeparse import parse_date, parse_time
from sidequest.core.tz import get_zone
from sidequest.scheduler.signal import ScheduleSignal
from sidequest.services import meta
from sidequest.services import settings as user_settings
from sidequest.services.actor import Actor
from sidequest.services.dto import DueInput
from sidequest.services.effects import DeleteMessage, Effect, Outcome
from sidequest.services.uow import Uow, UowFactory

log = logging.getLogger(__name__)

NO_MENTIONS = discord.AllowedMentions.none()

NOT_IN_SERVER = (
    "The server list only works in a server where Sidequest is added. Use `scope: Personal` here."
)
PICK_FROM_LIST = "Pick a to-do from the list that appears while you type."


# --- dependencies ------------------------------------------------------------------------


class CommandHashStore(Protocol):
    """Where the hash of the last globally synced command payload is kept."""

    async def load(self) -> str | None: ...

    async def save(self, value: str) -> None: ...


class DbCommandHashStore:
    def __init__(self, uows: UowFactory) -> None:
        self._uows = uows

    async def load(self) -> str | None:
        async with self._uows() as uow:
            return await meta.get(uow, meta.COMMAND_HASH)

    async def save(self, value: str) -> None:
        async with self._uows() as uow:
            await meta.put(uow, meta.COMMAND_HASH, value)


@dataclass(frozen=True)
class BotDeps:
    uows: UowFactory
    signal: ScheduleSignal
    command_hashes: CommandHashStore
    engine: AsyncEngine | None = None
    """Disposed when the client closes (None in tests)."""


class _HasDeps(Protocol):
    deps: BotDeps


def deps(interaction: discord.Interaction) -> BotDeps:
    return cast(_HasDeps, interaction.client).deps


def uows(interaction: discord.Interaction) -> UowFactory:
    return deps(interaction).uows


# --- who and where -----------------------------------------------------------------------


def actor_from(interaction: discord.Interaction) -> Actor:
    """`guild_id` only counts where the bot itself is installed in that guild; in a server
    where the user merely has the app user-installed there is no server list."""
    guild_id = interaction.guild_id if interaction.is_guild_integration() else None
    perms = interaction.permissions
    return Actor(
        user_id=interaction.user.id,
        guild_id=guild_id,
        can_manage_guild=guild_id is not None and (perms.manage_guild or perms.administrator),
        origin="discord",
    )


class ScopeOption(enum.Enum):
    """The `scope` option. Member names are what Discord shows."""

    Server = "server"
    Personal = "personal"


def resolve_scope(actor: Actor, choice: ScopeOption | None) -> Scope:
    """Default: the server list where the bot is installed, else the personal list."""
    if choice is None:
        return Scope.SERVER if actor.guild_id is not None else Scope.PERSONAL
    if choice is ScopeOption.Server and actor.guild_id is None:
        raise InvalidOperation(NOT_IN_SERVER)
    return Scope(choice.value)


# --- option parsing ----------------------------------------------------------------------


def parse_id(value: str, message: str = PICK_FROM_LIST) -> int:
    """Autocomplete options carry the id as text; free text that isn't an id is an error."""
    text = value.strip()
    if not text.isdigit():
        raise InvalidOperation(message)
    return int(text)


def user_ids(users: Iterable[discord.abc.User | None]) -> list[int] | None:
    """The `assignee` options → ids, or None when none were given (service default)."""
    ids = [u.id for u in users if u is not None]
    return ids or None


async def zone_name(uow: Uow, actor: Actor, override: str | None) -> str:
    """The timezone a command works in: the override, else the user's, else the default."""
    if override is not None and override.strip():
        return get_zone(override).key
    name, _ = await user_settings.get_user_timezone(uow, actor.user_id)
    return name


async def due_input(
    uow: Uow, actor: Actor, date_text: str | None, time_text: str | None, tz: str | None
) -> DueInput:
    """Parse the `date`/`time` options. `today`/`tomorrow` are relative to the zone the
    to-do will use."""
    parsed_time = parse_time(time_text) if time_text else None
    parsed_date: date | None = None
    if date_text:
        zone = get_zone(await zone_name(uow, actor, tz))
        parsed_date = parse_date(date_text, uow.clock.now().astimezone(zone).date())
    return DueInput(date=parsed_date, time=parsed_time)


# --- after a service call ----------------------------------------------------------------


async def run_effects(client: discord.Client, effects: Sequence[Effect]) -> None:
    for effect in effects:
        match effect:
            case DeleteMessage(channel_id=channel_id, message_id=message_id):
                message = client.get_partial_messageable(channel_id).get_partial_message(message_id)
                try:
                    await message.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass  # already gone, or the channel is no longer reachable
                except discord.HTTPException as exc:
                    log.warning(
                        "Could not delete message %s in %s: %s", message_id, channel_id, exc
                    )


async def apply[T](interaction: discord.Interaction, outcome: Outcome[T]) -> T:
    """Run the outcome's effects, wake the scheduler if needed, return the value."""
    await run_effects(interaction.client, outcome.effects)
    if outcome.changed_schedule:
        deps(interaction).signal.wake()
    return outcome.value


async def collect_notes(uow: Uow, user_id: int) -> list[str]:
    """One-line notes shown once before a command's reply (D25, D26)."""
    notes: list[str] = []
    failed_at = await user_settings.consume_dm_failure(uow, user_id)
    if failed_at is not None:
        notes.append(
            f"⚠️ A personal reminder couldn't be sent to you by DM ({ts(failed_at, 'R')}). "
            "Share a server with Sidequest and allow DMs from its members."
        )
    if await user_settings.consume_tz_hint(uow, user_id):
        notes.append(
            f"ℹ️ Times use {uow.default_timezone} until you set your timezone with "
            "`/settings timezone`."
        )
    return notes


# --- responding --------------------------------------------------------------------------


async def defer(interaction: discord.Interaction, *, ephemeral: bool = True) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=ephemeral, thinking=True)


def with_notes(notes: Sequence[str], content: str | None) -> str | None:
    parts = [*notes, content] if content else list(notes)
    return "\n".join(parts) or None


async def reply(
    interaction: discord.Interaction,
    content: str | None = None,
    *,
    notes: Sequence[str] = (),
    embed: discord.Embed | None = None,
    view: discord.ui.View | None = None,
    ephemeral: bool = True,
) -> discord.Message | None:
    """Send the response (or the follow-up after `defer`). Views that have a `message`
    attribute get the sent message, so they can disable themselves on timeout."""
    kwargs: dict[str, Any] = {
        "content": with_notes(notes, content),
        "allowed_mentions": NO_MENTIONS,
        "ephemeral": ephemeral,
    }
    if embed is not None:
        kwargs["embed"] = embed
    if view is not None:
        kwargs["view"] = view

    message: discord.Message | None
    if interaction.response.is_done():
        message = await interaction.followup.send(wait=True, **kwargs)
    else:
        await interaction.response.send_message(**kwargs)
        message = await interaction.original_response() if view is not None else None
    if view is not None and hasattr(view, "message"):
        view.message = message
    return message
