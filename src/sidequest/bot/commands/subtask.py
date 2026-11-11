"""`/todo subtask …`: checklist items on a to-do (`add`, `remove`)."""

import discord
from discord import app_commands

from sidequest.bot import adapter, autocomplete, options, render
from sidequest.core.limits import SUBTASKS_MAX
from sidequest.services import subtasks


def build_subtask_group() -> app_commands.Group:
    """A fresh `/todo subtask` group (fresh command objects, so several clients can coexist)."""
    group = app_commands.Group(name="subtask", description="Checklist items on a to-do")
    group.add_command(add_command())
    group.add_command(remove_command())
    return group


def add_command() -> app_commands.Command:  # type: ignore[type-arg]
    @app_commands.command(name="add", description="Add checklist items to a to-do")
    @app_commands.describe(
        todo="The to-do",
        items="Subtask titles separated by ; e.g. buy milk; call mum",
    )
    @app_commands.autocomplete(todo=autocomplete.todo)
    async def add(interaction: discord.Interaction, todo: str, items: str) -> None:
        await adapter.defer(interaction)
        actor = adapter.actor_from(interaction)
        titles = options.split_items(items)
        async with adapter.uows(interaction)() as uow:
            out = await subtasks.add(uow, actor, adapter.parse_id(todo), titles)
            notes = await adapter.collect_notes(uow, actor.user_id)
        view = await adapter.apply(interaction, out)
        await adapter.reply(
            interaction,
            f"➕ Added {len(titles)} subtask(s) to **{render.esc(view.title)}** "
            f"({len(view.subtasks)}/{SUBTASKS_MAX}).",
            notes=notes,
        )

    return add


def remove_command() -> app_commands.Command:  # type: ignore[type-arg]
    @app_commands.command(name="remove", description="Remove a checklist item")
    @app_commands.describe(todo="The to-do", subtask="The subtask")
    @app_commands.autocomplete(todo=autocomplete.todo, subtask=autocomplete.subtask)
    async def remove(interaction: discord.Interaction, todo: str, subtask: str) -> None:
        await adapter.defer(interaction)
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            out = await subtasks.remove(
                uow,
                actor,
                adapter.parse_id(
                    subtask, "Pick a subtask from the list that appears while you type."
                ),
            )
            notes = await adapter.collect_notes(uow, actor.user_id)
        view = await adapter.apply(interaction, out)
        await adapter.reply(
            interaction,
            f"➖ Removed the subtask from **{render.esc(view.title)}**.",
            notes=notes,
        )

    return remove
