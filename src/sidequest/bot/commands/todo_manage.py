"""`/todo done|details|assign|delete`: act on one existing to-do (picked from autocomplete)."""

import discord
from discord import app_commands

from sidequest.bot import adapter, autocomplete, render
from sidequest.bot.views.assign import AssignView
from sidequest.bot.views.confirm import DeleteConfirmView
from sidequest.bot.views.modals import DetailsModal
from sidequest.core.enums import Scope
from sidequest.core.errors import Forbidden, InvalidOperation
from sidequest.core.limits import ASSIGNEES_MAX
from sidequest.services import todos

CANT_EDIT = "Only the creator, an assignee or someone with Manage Server can change this to-do."


def commands() -> list[app_commands.Command]:  # type: ignore[type-arg]
    return [done_command(), details_command(), assign_command(), delete_command()]


def done_command() -> app_commands.Command:  # type: ignore[type-arg]
    @app_commands.command(name="done", description="Check off a to-do")
    @app_commands.describe(todo="The to-do")
    @app_commands.autocomplete(todo=autocomplete.todo)
    async def done(interaction: discord.Interaction, todo: str) -> None:
        await adapter.defer(interaction)
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            out = await todos.complete(uow, actor, adapter.parse_id(todo))
            notes = await adapter.collect_notes(uow, actor.user_id)
        view = await adapter.apply(interaction, out)
        await adapter.reply(interaction, render.done_text(view), notes=notes)

    return done


def details_command() -> app_commands.Command:  # type: ignore[type-arg]
    @app_commands.command(name="details", description="Write or change a to-do's details")
    @app_commands.describe(todo="The to-do")
    @app_commands.autocomplete(todo=autocomplete.todo)
    async def details(interaction: discord.Interaction, todo: str) -> None:
        # No defer: the modal must be the first response.
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            view = await todos.get(uow, actor, adapter.parse_id(todo))
        if not view.can_edit:
            raise Forbidden(CANT_EDIT)
        await interaction.response.send_modal(DetailsModal(view.id, view.details))

    return details


def assign_command() -> app_commands.Command:  # type: ignore[type-arg]
    @app_commands.command(name="assign", description="Choose who should do a server to-do")
    @app_commands.describe(todo="The to-do")
    @app_commands.autocomplete(todo=autocomplete.todo)
    async def assign(interaction: discord.Interaction, todo: str) -> None:
        await adapter.defer(interaction)
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            view = await todos.get(uow, actor, adapter.parse_id(todo))
            notes = await adapter.collect_notes(uow, actor.user_id)
        if view.scope != Scope.SERVER:
            raise InvalidOperation("Personal to-dos can't have assignees.")
        if not view.can_edit:
            raise Forbidden(CANT_EDIT)
        await adapter.reply(
            interaction,
            f"Who should do **{render.esc(view.title)}**? Pick up to {ASSIGNEES_MAX} people.",
            notes=notes,
            view=AssignView(interaction.user.id, view.id, view.title, view.assignee_ids),
        )

    return assign


def delete_command() -> app_commands.Command:  # type: ignore[type-arg]
    @app_commands.command(name="delete", description="Delete a to-do")
    @app_commands.describe(todo="The to-do")
    @app_commands.autocomplete(todo=autocomplete.todo)
    async def delete(interaction: discord.Interaction, todo: str) -> None:
        await adapter.defer(interaction)
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            view = await todos.get(uow, actor, adapter.parse_id(todo))
            notes = await adapter.collect_notes(uow, actor.user_id)
        if not view.can_edit:
            raise Forbidden(CANT_EDIT)
        await adapter.reply(
            interaction,
            f"Delete **{render.esc(view.title)}**? This can't be undone.",
            notes=notes,
            view=DeleteConfirmView(interaction.user.id, view.id, view.title),
        )

    return delete
