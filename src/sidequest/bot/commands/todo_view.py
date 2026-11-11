"""`/todo show` and `/todo upcoming`."""

import discord
from discord import app_commands

from sidequest.bot import adapter, autocomplete, render
from sidequest.bot.adapter import ScopeOption
from sidequest.bot.views import upcoming as upcoming_view
from sidequest.bot.views.show import ShowView
from sidequest.bot.views.upcoming import ScopePickView, UpcomingView
from sidequest.services import todos


def show_command() -> app_commands.Command:  # type: ignore[type-arg]
    @app_commands.command(name="show", description="Show a to-do with its details and subtasks")
    @app_commands.describe(todo="The to-do")
    @app_commands.autocomplete(todo=autocomplete.todo)
    async def show(interaction: discord.Interaction, todo: str) -> None:
        await adapter.defer(interaction)
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            view = await todos.get(uow, actor, adapter.parse_id(todo))
            notes = await adapter.collect_notes(uow, actor.user_id)
        components = ShowView(interaction.user.id, view)
        await adapter.reply(
            interaction,
            notes=notes,
            embed=render.todo_embed(view),
            view=components if components.children else None,
        )

    return show


def upcoming_command() -> app_commands.Command:  # type: ignore[type-arg]
    @app_commands.command(
        name="upcoming", description="Timed to-dos coming up; check them off early"
    )
    @app_commands.describe(
        scope="Server list, your personal list, or leave empty to choose with buttons",
        days="How many days ahead (default 7)",
    )
    async def upcoming(
        interaction: discord.Interaction,
        scope: ScopeOption | None = None,
        days: app_commands.Range[int, 1, 31] = 7,
    ) -> None:
        actor = adapter.actor_from(interaction)
        if scope is None and actor.guild_id is not None:
            # In a server both lists apply: ask which one (D35).
            await adapter.defer(interaction)
            async with adapter.uows(interaction)() as uow:
                notes = await adapter.collect_notes(uow, actor.user_id)
            await adapter.reply(
                interaction,
                "Which upcoming to-dos do you want to see?",
                notes=notes,
                view=ScopePickView(interaction.user.id, days),
            )
            return

        scope_ = adapter.resolve_scope(actor, scope)
        await adapter.defer(interaction)
        async with adapter.uows(interaction)() as uow:
            items = await upcoming_view.load(uow, actor, scope_, days)
            notes = await adapter.collect_notes(uow, actor.user_id)
        await adapter.reply(
            interaction,
            notes=notes,
            embed=render.upcoming_embed(items, days, upcoming_view.LIMIT),
            view=UpcomingView(interaction.user.id, scope_, days, items) if items else None,
        )

    return upcoming
