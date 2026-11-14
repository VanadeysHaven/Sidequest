"""`/todo suspend` and `/todo unsuspend`: no reminders between two dates (D81–D89)."""

from datetime import date

import discord
from discord import app_commands

from sidequest.bot import adapter, autocomplete, render
from sidequest.bot.commands import common
from sidequest.bot.views.suspend import SuspendConfirmView
from sidequest.core.errors import InvalidOperation
from sidequest.services import suspensions, todos

PICK_SUSPENSION = "Pick a suspension from the list that appears while you type."


def commands() -> list[app_commands.Command]:  # type: ignore[type-arg]
    return [suspend_command(), unsuspend_command()]


def suspend_command() -> app_commands.Command:  # type: ignore[type-arg]
    @app_commands.command(
        name="suspend", description="Skip a repeating to-do's reminders for a while"
    )
    @app_commands.describe(
        todo="The repeating to-do",
        start="First day without reminders (a date or a weekday); alone: just that day",
        end="Last day without reminders (a date or a weekday); alone: from now until then",
    )
    @app_commands.autocomplete(todo=autocomplete.todo)
    async def suspend(
        interaction: discord.Interaction,
        todo: str,
        start: str | None = None,
        end: str | None = None,
    ) -> None:
        common.check_options(date_text=start)
        common.check_options(date_text=end)
        todo_id = adapter.parse_id(todo)
        await adapter.defer(interaction)
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            current = await todos.get(uow, actor, todo_id)
            # D70/D71: weekday names in the to-do's zone, today counts.
            first = await adapter.local_date(uow, actor, start, current.timezone) if start else None
            last = await adapter.local_date(uow, actor, end, current.timezone) if end else None
            preview = await suspensions.preview(uow, actor, todo_id, first, last)
            notes = await adapter.collect_notes(uow, actor.user_id)
        confirm = SuspendConfirmView(interaction.user.id, todo_id, preview)
        await adapter.reply(interaction, confirm.text(), notes=notes, view=confirm)

    return suspend


def parse_suspension(value: str) -> date:
    """The `suspension` option (autocomplete, value = its start as YYYY-MM-DD)."""
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise InvalidOperation(PICK_SUSPENSION) from None


def unsuspend_command() -> app_commands.Command:  # type: ignore[type-arg]
    @app_commands.command(name="unsuspend", description="Cancel a suspension of a repeating to-do")
    @app_commands.describe(todo="The repeating to-do", suspension="The suspension to cancel")
    @app_commands.autocomplete(todo=autocomplete.todo, suspension=autocomplete.suspension)
    async def unsuspend(interaction: discord.Interaction, todo: str, suspension: str) -> None:
        todo_id = adapter.parse_id(todo)
        start = parse_suspension(suspension)
        await adapter.defer(interaction)
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            out = await suspensions.unsuspend(uow, actor, todo_id, start)
            notes = await adapter.collect_notes(uow, actor.user_id)
        change = await adapter.apply(interaction, out)
        await adapter.reply(interaction, render.unsuspended_text(change), notes=notes)

    return unsuspend
