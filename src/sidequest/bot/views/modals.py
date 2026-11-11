"""Modals: create-with-details and edit details."""

from collections.abc import Awaitable, Callable

import discord

from sidequest.bot import adapter, render
from sidequest.bot.views.base import BaseModal
from sidequest.core.limits import DETAILS_MAX, TITLE_MAX
from sidequest.services import todos

type CreateSubmit = Callable[[discord.Interaction, str, str | None], Awaitable[None]]


def _details_input(default: str | None) -> discord.ui.TextInput["BaseModal"]:
    return discord.ui.TextInput(
        label="Details",
        style=discord.TextStyle.paragraph,
        default=default,
        required=False,
        max_length=DETAILS_MAX,
        placeholder="Optional. Several lines are fine.",
    )


class CreateWithDetailsModal(BaseModal):
    """`details:True` on a create command: re-shows the title and asks for details. The
    to-do is created on submit by `submit`, which carries the command's other options."""

    def __init__(self, title: str, submit: CreateSubmit) -> None:
        super().__init__(title="Add to-do")
        self.title_input: discord.ui.TextInput[CreateWithDetailsModal] = discord.ui.TextInput(
            label="Title", default=title, max_length=TITLE_MAX
        )
        self.details_input = _details_input(None)
        self.add_item(self.title_input)
        self.add_item(self.details_input)
        self._submit = submit

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._submit(interaction, self.title_input.value, self.details_input.value or None)


class DetailsModal(BaseModal):
    """Edit a to-do's details; an empty box removes them."""

    def __init__(self, todo_id: int, current: str | None) -> None:
        super().__init__(title="Details")
        self.todo_id = todo_id
        self.details_input = _details_input(current)
        self.add_item(self.details_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await adapter.defer(interaction)
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            out = await todos.set_details(uow, actor, self.todo_id, self.details_input.value)
            notes = await adapter.collect_notes(uow, actor.user_id)
        todo = await adapter.apply(interaction, out)
        verb = "saved" if todo.details else "removed"
        await adapter.reply(
            interaction, f"📝 Details {verb} for **{render.esc(todo.title)}**.", notes=notes
        )
