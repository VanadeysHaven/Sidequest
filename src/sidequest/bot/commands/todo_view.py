"""`/todo show` and `/todo upcoming`."""

import discord
from discord import app_commands

from sidequest.bot import adapter, autocomplete, render
from sidequest.bot.views import upcoming as upcoming_view
from sidequest.bot.views.show import ShowView
from sidequest.bot.views.upcoming import UpcomingView
from sidequest.core.errors import InvalidOperation
from sidequest.services import lists, settings, todos

NEEDS_LIST = "Pick a list with `list:`, or set a default with `/settings default-list`."


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
        list_="Which list (default: your own default list)",
        days="How many days ahead (default 7)",
    )
    @app_commands.rename(list_="list")
    @app_commands.autocomplete(list_=autocomplete.todo_list)
    async def upcoming(
        interaction: discord.Interaction,
        list_: str | None = None,
        days: app_commands.Range[int, 1, 31] = 7,
    ) -> None:
        actor = adapter.actor_from(interaction)
        list_id = adapter.parse_list_id(list_)
        await adapter.defer(interaction)
        async with adapter.uows(interaction)() as uow:
            if list_id is None:
                # D49: only the user's own setting, not the server's fallback list.
                list_id = await settings.own_default_list_id(uow, actor)
                if list_id is None:
                    raise InvalidOperation(NEEDS_LIST)
            lst = await lists.get(uow, actor, list_id)
            items = await upcoming_view.load(uow, actor, lst.id, days)
            notes = await adapter.collect_notes(uow, actor.user_id)
        view = UpcomingView(interaction.user.id, lst.id, lst.name, days, items)
        await adapter.reply(
            interaction,
            notes=notes,
            embed=view.embed(items),
            view=view if view.children else None,
        )

    return upcoming
