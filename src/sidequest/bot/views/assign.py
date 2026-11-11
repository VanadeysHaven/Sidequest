"""Choosing the assignees of a server to-do."""

from collections.abc import Sequence

import discord

from sidequest.bot import adapter, render
from sidequest.bot.views.base import BaseView
from sidequest.core.errors import InvalidOperation
from sidequest.core.limits import ASSIGNEES_MAX
from sidequest.services import todos


class AssignView(BaseView):
    def __init__(self, owner_id: int, todo_id: int, title: str, current: Sequence[int]) -> None:
        super().__init__(owner_id)
        self.todo_id = todo_id
        self.title = title
        self.select = discord.ui.UserSelect(
            placeholder="Assignees",
            min_values=1,
            max_values=ASSIGNEES_MAX,
            default_values=[discord.Object(id=u) for u in current],
        )
        self.select.callback = self._chosen
        self.add_item(self.select)

    async def _chosen(self, interaction: discord.Interaction) -> None:
        ids = [u.id for u in self.select.values if not u.bot]
        if not ids:
            raise InvalidOperation("Pick at least one person (bots can't be assigned).")
        await interaction.response.defer()
        async with adapter.uows(interaction)() as uow:
            out = await todos.set_assignees(uow, adapter.actor_from(interaction), self.todo_id, ids)
        view = await adapter.apply(interaction, out)
        await interaction.edit_original_response(
            content=(
                f"👥 **{render.esc(view.title)}** is now assigned to "
                f"{render.mentions(view.assignee_ids)}."
            ),
            view=None,
            allowed_mentions=adapter.NO_MENTIONS,
        )
        self.stop()
