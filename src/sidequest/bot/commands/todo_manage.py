"""`/todo done|details|assign|delete|move`: act on one existing to-do (from autocomplete)."""

import discord
from discord import app_commands

from sidequest.bot import adapter, autocomplete, render
from sidequest.bot.views.assign import AssignView
from sidequest.bot.views.confirm import (
    CheckOffConfirmView,
    DeleteConfirmView,
    must_confirm,
    not_checked_off,
)
from sidequest.bot.views.modals import DetailsModal
from sidequest.bot.views.undo import UndoView
from sidequest.core.errors import Forbidden
from sidequest.core.limits import ASSIGNEES_MAX
from sidequest.services import todos
from sidequest.services.dto import TodoView


def cant_edit(view: TodoView) -> Forbidden:
    return Forbidden(
        f"Only the owner and collaborators of **{render.esc(view.list_name)}** "
        "(or someone with Manage Server) can change its to-dos."
    )


def commands() -> list[app_commands.Command]:  # type: ignore[type-arg]
    return [done_command(), details_command(), assign_command(), delete_command(), move_command()]


def done_command() -> app_commands.Command:  # type: ignore[type-arg]
    @app_commands.command(name="done", description="Check off a to-do")
    @app_commands.describe(todo="The to-do")
    @app_commands.autocomplete(todo=autocomplete.todo)
    async def done(interaction: discord.Interaction, todo: str) -> None:
        todo_id = adapter.parse_id(todo)
        await adapter.defer(interaction)
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            current = await todos.get(uow, actor, todo_id)
            notes = await adapter.collect_notes(uow, actor.user_id)
        if must_confirm(actor.user_id, current):
            # D67: not an assignee, so ask first.
            async def confirmed(confirm: discord.Interaction) -> None:
                await confirm.response.defer()
                text, undo_view = await _check_off(confirm, todo_id)
                undo_view.message = await confirm.edit_original_response(
                    content=text, view=undo_view, allowed_mentions=adapter.NO_MENTIONS
                )

            await adapter.reply(
                interaction,
                render.check_off_prompt(current),
                notes=notes,
                view=CheckOffConfirmView(interaction.user.id, confirmed, not_checked_off),
            )
            return
        text, undo_view = await _check_off(interaction, todo_id)
        await adapter.reply(interaction, text, notes=notes, view=undo_view)

    return done


async def _check_off(interaction: discord.Interaction, todo_id: int) -> tuple[str, UndoView]:
    """Check off; returns the reply text and its Undo button (D60)."""
    async with adapter.uows(interaction)() as uow:
        out = await todos.complete(uow, adapter.actor_from(interaction), todo_id)
    checked = await adapter.apply(interaction, out)
    return render.done_text(checked.todo), UndoView(interaction.user.id, checked.undo)


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
            raise cant_edit(view)
        await interaction.response.send_modal(DetailsModal(view.id, view.details))

    return details


def assign_command() -> app_commands.Command:  # type: ignore[type-arg]
    @app_commands.command(name="assign", description="Choose who should do a to-do")
    @app_commands.describe(todo="The to-do")
    @app_commands.autocomplete(todo=autocomplete.todo)
    async def assign(interaction: discord.Interaction, todo: str) -> None:
        await adapter.defer(interaction)
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            view = await todos.get(uow, actor, adapter.parse_id(todo))
            notes = await adapter.collect_notes(uow, actor.user_id)
        if not view.can_edit:
            raise cant_edit(view)
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
            raise cant_edit(view)
        await adapter.reply(
            interaction,
            f"Delete **{render.esc(view.title)}**? This can't be undone.",
            notes=notes,
            view=DeleteConfirmView(interaction.user.id, view.id, view.title),
        )

    return delete


def move_command() -> app_commands.Command:  # type: ignore[type-arg]
    @app_commands.command(name="move", description="Move a to-do to another list")
    @app_commands.describe(todo="The to-do", list_="The list to move it to")
    @app_commands.rename(list_="list")
    @app_commands.autocomplete(todo=autocomplete.todo, list_=autocomplete.todo_list)
    async def move(interaction: discord.Interaction, todo: str, list_: str) -> None:
        todo_id = adapter.parse_id(todo)
        list_id = adapter.parse_id(list_, adapter.PICK_A_LIST)
        await adapter.defer(interaction)
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            out = await todos.move(uow, actor, todo_id, list_id)
            notes = await adapter.collect_notes(uow, actor.user_id)
        view = await adapter.apply(interaction, out)
        await adapter.reply(interaction, render.moved_text(view), notes=notes)

    return move
