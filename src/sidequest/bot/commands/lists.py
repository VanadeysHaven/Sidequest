"""`/lists …`: a server's named lists (S8: D41–D52)."""

import discord
from discord import app_commands

from sidequest.bot import adapter, autocomplete, render
from sidequest.bot.commands.common import GUILD_CONTEXTS, GUILD_INSTALLS
from sidequest.bot.views.collaborators import CollaboratorsView
from sidequest.bot.views.confirm import TransferConfirmView
from sidequest.bot.views.list_delete import ListDeleteView
from sidequest.core.errors import Forbidden, InvalidOperation
from sidequest.core.limits import LIST_NAME_MAX
from sidequest.services import lists
from sidequest.services.dto import ListView

ListName = app_commands.Range[str, 1, LIST_NAME_MAX]


def _require_manage(lst: ListView, fallback: str) -> None:
    """The same checks the service makes, before showing a select or a confirmation."""
    if lst.is_fallback:
        raise InvalidOperation(fallback.format(name=f"**{render.esc(lst.name)}**"))
    if not lst.can_manage:
        raise Forbidden(
            f"Only the owner of **{render.esc(lst.name)}** or someone with Manage Server "
            "can do that."
        )


def build_lists_group() -> app_commands.Group:
    group = app_commands.Group(
        name="lists",
        description="This server's to-do lists",
        allowed_installs=GUILD_INSTALLS,
        allowed_contexts=GUILD_CONTEXTS,
    )

    @group.command(name="create", description="Create a list; you become its owner")
    @app_commands.describe(name="Name of the list (max 50 characters)")
    async def create(interaction: discord.Interaction, name: ListName) -> None:
        await adapter.defer(interaction)
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            lst = await lists.create(uow, actor, name)
            notes = await adapter.collect_notes(uow, actor.user_id)
        await adapter.reply(
            interaction,
            f"📋 Created list **{render.esc(lst.name)}**. Only you can add to-dos to it so "
            "far; add people with `/lists collaborators`.",
            notes=notes,
        )

    @group.command(name="rename", description="Rename a list (owner or Manage Server)")
    @app_commands.describe(list_="The list", name="New name (max 50 characters)")
    @app_commands.rename(list_="list")
    @app_commands.autocomplete(list_=autocomplete.todo_list)
    async def rename(interaction: discord.Interaction, list_: str, name: ListName) -> None:
        list_id = adapter.parse_id(list_, adapter.PICK_A_LIST)
        await adapter.defer(interaction)
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            old = await lists.get(uow, actor, list_id)
            lst = await lists.rename(uow, actor, list_id, name)
            notes = await adapter.collect_notes(uow, actor.user_id)
        await adapter.reply(
            interaction,
            f"✏️ Renamed **{render.esc(old.name)}** to **{render.esc(lst.name)}**.",
            notes=notes,
        )

    @group.command(name="delete", description="Delete a list (owner or Manage Server)")
    @app_commands.describe(list_="The list")
    @app_commands.rename(list_="list")
    @app_commands.autocomplete(list_=autocomplete.todo_list)
    async def delete(interaction: discord.Interaction, list_: str) -> None:
        list_id = adapter.parse_id(list_, adapter.PICK_A_LIST)
        await adapter.defer(interaction)
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            preview = await lists.delete_preview(uow, actor, list_id)
            notes = await adapter.collect_notes(uow, actor.user_id)
        view = ListDeleteView(interaction.user.id, preview)
        await adapter.reply(interaction, view.prompt(), notes=notes, view=view)

    @group.command(
        name="collaborators", description="Choose who may work on a list (owner or Manage Server)"
    )
    @app_commands.describe(list_="The list")
    @app_commands.rename(list_="list")
    @app_commands.autocomplete(list_=autocomplete.todo_list)
    async def collaborators(interaction: discord.Interaction, list_: str) -> None:
        list_id = adapter.parse_id(list_, adapter.PICK_A_LIST)
        await adapter.defer(interaction)
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            lst = await lists.get(uow, actor, list_id)
            notes = await adapter.collect_notes(uow, actor.user_id)
        _require_manage(lst, lists.FALLBACK_NO_COLLABORATORS)
        await adapter.reply(
            interaction,
            f"Who may add, change and check off to-dos on **{render.esc(lst.name)}**? "
            "The owner always can.",
            notes=notes,
            view=CollaboratorsView(interaction.user.id, lst),
        )

    @group.command(name="transfer", description="Give a list a new owner (owner or Manage Server)")
    @app_commands.describe(list_="The list", user="The new owner")
    @app_commands.rename(list_="list")
    @app_commands.autocomplete(list_=autocomplete.todo_list)
    async def transfer(interaction: discord.Interaction, list_: str, user: discord.User) -> None:
        list_id = adapter.parse_id(list_, adapter.PICK_A_LIST)
        if user.bot:
            raise InvalidOperation("A bot can't own a list.")
        if not isinstance(user, discord.Member):
            raise InvalidOperation(f"{user.mention} isn't a member of this server.")
        await adapter.defer(interaction)
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            lst = await lists.get(uow, actor, list_id)
            notes = await adapter.collect_notes(uow, actor.user_id)
        _require_manage(lst, lists.FALLBACK_NO_TRANSFER)
        if lst.owner_id == user.id:
            raise InvalidOperation(f"{user.mention} already owns **{render.esc(lst.name)}**.")
        await adapter.reply(
            interaction,
            f"Make {user.mention} the owner of **{render.esc(lst.name)}**? The current owner "
            "stays on as a collaborator.",
            notes=notes,
            view=TransferConfirmView(interaction.user.id, lst.id, user.id),
        )

    @group.command(name="show", description="All lists of this server")
    async def show(interaction: discord.Interaction) -> None:
        await adapter.defer(interaction)
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            found = await lists.list_lists(uow, actor)
            notes = await adapter.collect_notes(uow, actor.user_id)
        await adapter.reply(interaction, notes=notes, embed=render.lists_embed(found))

    return group
