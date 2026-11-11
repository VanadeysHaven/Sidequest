"""`/todo list`: the open to-dos of the server or personal list, optionally posted publicly."""

import enum
from typing import cast

import discord
from discord import app_commands

from sidequest.bot import adapter, render
from sidequest.bot.adapter import ScopeOption
from sidequest.bot.views.listing import ListView
from sidequest.core.enums import Scope
from sidequest.core.errors import InvalidOperation
from sidequest.services import todos
from sidequest.services.dto import ListFilter


class ShowOption(enum.Enum):
    """The `show` option. Member names are what Discord shows."""

    All = "all"
    Timed = "timed"
    Untimed = "untimed"


def list_command() -> app_commands.Command:  # type: ignore[type-arg]
    @app_commands.command(name="list", description="Show open to-dos")
    @app_commands.describe(
        scope="Server list or your personal list",
        show="Which to-dos (default: all open)",
        post="Post the server list in this channel for everyone",
    )
    async def todo_list(
        interaction: discord.Interaction,
        scope: ScopeOption | None = None,
        show: ShowOption | None = None,
        post: bool = False,
    ) -> None:
        actor = adapter.actor_from(interaction)
        scope_ = adapter.resolve_scope(actor, scope)
        if post and scope_ != Scope.SERVER:
            raise InvalidOperation("Only the server list can be posted. Use scope: Server.")
        filter_ = cast(ListFilter, show.value if show else "all")
        await adapter.defer(interaction, ephemeral=not post)
        async with adapter.uows(interaction)() as uow:
            page = await todos.list_todos(uow, actor, scope_, filter_)
            notes = await adapter.collect_notes(uow, actor.user_id)
        embed = render.list_embed(page, scope_, filter_)
        view = (
            ListView(None if post else interaction.user.id, scope_, filter_, page)
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
