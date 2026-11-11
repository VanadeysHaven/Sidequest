"""Confirmation before a to-do is deleted."""

import discord

from sidequest.bot import adapter, render
from sidequest.bot.views.base import BaseView
from sidequest.services import todos


class DeleteConfirmView(BaseView):
    def __init__(self, owner_id: int, todo_id: int, title: str) -> None:
        super().__init__(owner_id)
        self.todo_id = todo_id
        self.title = title

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def delete_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["DeleteConfirmView"]
    ) -> None:
        await interaction.response.defer()
        async with adapter.uows(interaction)() as uow:
            out = await todos.delete(uow, adapter.actor_from(interaction), self.todo_id)
        await adapter.apply(interaction, out)
        await interaction.edit_original_response(
            content=f"🗑️ Deleted **{render.esc(self.title)}**.",
            view=None,
            allowed_mentions=adapter.NO_MENTIONS,
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["DeleteConfirmView"]
    ) -> None:
        await interaction.response.edit_message(content="Kept it.", view=None)
        self.stop()
