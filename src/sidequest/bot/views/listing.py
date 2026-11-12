"""Paging buttons under `/todo list`."""

import discord

from sidequest.bot import adapter, render
from sidequest.bot.views.base import BaseView
from sidequest.services import todos
from sidequest.services.dto import ListFilter, Page, TodoView


class ListPageView(BaseView):
    """Prev/Next over one list. A public list (owner_id None) can be paged by anyone."""

    def __init__(
        self,
        owner_id: int | None,
        list_id: int,
        list_name: str,
        filter: ListFilter,
        page: Page[TodoView],
    ) -> None:
        super().__init__(owner_id)
        self.list_id = list_id
        self.list_name = list_name
        self.filter = filter
        self.page_number = page.page
        self._update_buttons(page)

    def _update_buttons(self, page: Page[TodoView]) -> None:
        self.prev_button.disabled = page.page == 0
        self.next_button.disabled = not page.has_next

    async def _show(self, interaction: discord.Interaction, number: int) -> None:
        await interaction.response.defer()
        actor = adapter.actor_from(interaction)
        async with adapter.uows(interaction)() as uow:
            page = await todos.list_todos(uow, actor, self.list_id, self.filter, page=number)
        self.page_number = page.page
        self._update_buttons(page)
        await interaction.edit_original_response(
            embed=render.list_embed(page, self.list_name, self.filter), view=self
        )

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self._show(interaction, self.page_number - 1)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self._show(interaction, self.page_number + 1)
