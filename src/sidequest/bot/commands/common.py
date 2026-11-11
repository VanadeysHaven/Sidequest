"""Shared pieces of the slash commands: install contexts, option descriptions, create flow."""

from collections.abc import Awaitable, Callable
from datetime import date

import discord
from discord import app_commands

from sidequest.bot import adapter, render
from sidequest.bot.adapter import ScopeOption
from sidequest.bot.views.modals import CreateWithDetailsModal
from sidequest.core.timeparse import parse_date, parse_time
from sidequest.core.tz import get_zone
from sidequest.services.actor import Actor
from sidequest.services.dto import TodoView
from sidequest.services.effects import Outcome
from sidequest.services.uow import Uow

# /todo and /settings: guild + user installs; servers, DMs with the bot, group DMs.
ANYWHERE_INSTALLS = app_commands.AppInstallationType(guild=True, user=True)
ANYWHERE_CONTEXTS = app_commands.AppCommandContext(
    guild=True, dm_channel=True, private_channel=True
)

# Descriptions of the options every create command shares (stack with its own `describe`).
CREATE_DESCRIPTIONS: dict[str, str] = {
    "title": "What needs doing (max 200 characters)",
    "timezone": "Timezone for this to-do (default: yours)",
    "assignee": "Who should do it (server list only; default: you)",
    "assignee2": "Another assignee",
    "assignee3": "Another assignee",
    "scope": "Server list or your personal list (default: server list in a server)",
    "details": "Open a form for longer, multi-line details",
}

# Plain assignment, not `type`: discord.py must see the Range itself in annotations.
Title = app_commands.Range[str, 1, 200]
type Create = Callable[[Uow, Actor, str, str | None], Awaitable[Outcome[TodoView]]]


def check_options(
    *,
    scope: ScopeOption | None = None,
    interaction: discord.Interaction | None = None,
    date_text: str | None = None,
    time_text: str | None = None,
    timezone: str | None = None,
) -> None:
    """Validate what can be checked without the database, before a modal opens, so the
    user doesn't type details only to hit a typo afterwards."""
    if interaction is not None:
        adapter.resolve_scope(adapter.actor_from(interaction), scope)
    if time_text:
        parse_time(time_text)
    if date_text:
        parse_date(date_text, date(2000, 1, 1))  # format only; resolved later in the right zone
    if timezone:
        get_zone(timezone)


async def create_flow(
    interaction: discord.Interaction, *, title: str, with_details: bool, create: Create
) -> None:
    """Run `create` now, or first ask for details in a modal (`details:True`)."""
    if not with_details:
        await _create(interaction, title, None, create)
        return

    async def submit(modal_interaction: discord.Interaction, new_title: str, details: str | None):
        await _create(modal_interaction, new_title, details, create)

    await interaction.response.send_modal(CreateWithDetailsModal(title, submit))


async def _create(
    interaction: discord.Interaction, title: str, details: str | None, create: Create
) -> None:
    await adapter.defer(interaction)
    actor = adapter.actor_from(interaction)
    async with adapter.uows(interaction)() as uow:
        out = await create(uow, actor, title, details)
        notes = await adapter.collect_notes(uow, actor.user_id)
    todo = await adapter.apply(interaction, out)
    await adapter.reply(interaction, render.created_text(todo), notes=notes)
