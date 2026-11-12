"""`/todo list`: the open to-dos of one list, optionally posted publicly (D49)."""

import enum
from typing import cast

import discord
from discord import app_commands

from sidequest.bot import adapter, autocomplete, render
from sidequest.bot.views.listing import ListPageView
from sidequest.services import lists, todos
from sidequest.services.dto import ListFilter


class ShowOption(enum.Enum):
    """The `show` option. Member names are what Discord shows."""

    All = "all"
    Timed = "timed"
    Untimed = "untimed"


def list_command() -> app_commands.Command:  # type: ignore[type-arg]
    @app_commands.command(name="list", description="Show the open to-dos of a list")
    @app_commands.describe(
        list_="Which list (default: your default list)",
        show="Which to-dos (default: all open)",
        post="Post the list in this channel for everyone",
    )
    @app_commands.rename(list_="list")
    @app_commands.autocomplete(list_=autocomplete.todo_list)
    async def todo_list(
        interaction: discord.Interaction,
        list_: str | None = None,
        show: ShowOption | None = None,
        post: bool = False,
    ) -> None:
        actor = adapter.actor_from(interaction)
        list_id = adapter.parse_list_id(list_)
        filter_ = cast(ListFilter, show.value if show else "all")
        await adapter.defer(interaction, ephemeral=not post)
        async with adapter.uows(interaction)() as uow:
            lst = await lists.get(uow, actor, list_id)
            page = await todos.list_todos(uow, actor, lst.id, filter_)
            notes = await adapter.collect_notes(uow, actor.user_id)
        embed = render.list_embed(page, lst.name, filter_)
        view = (
            ListPageView(None if post else interaction.user.id, lst.id, lst.name, filter_, page)
            if page.page_count > 1
            else None
        )
        if post:
            await adapter.reply(interaction, embed=embed, view=view, ephemeral=False)
            if notes:
                await interaction.followup.send(
                    adapter.with_notes(notes, None),
                    ephemeral=True,
                    allowed_mentions=adapter.NO_MENTIONS,
                )
        else:
            await adapter.reply(interaction, embed=embed, view=view, notes=notes)

    return todo_list
