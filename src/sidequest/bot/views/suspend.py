"""The confirmation of `/todo suspend` (D84): **Suspend** / **Cancel**, and ◀ Prev / Next ▶
through the skipped reminders when they don't fit on one page. 5 minutes."""

import discord

from sidequest.bot import adapter, render
from sidequest.bot.views.base import BaseView
from sidequest.services import suspensions
from sidequest.services.dto import SuspensionPreview


class SuspendConfirmView(BaseView):
    """Suspend checks everything again (D85); a refusal keeps the buttons, so Cancel still
    works. Paging only re-renders the preview (no database call)."""

    def __init__(self, owner_id: int, todo_id: int, preview: SuspensionPreview) -> None:
        super().__init__(owner_id)
        self.todo_id = todo_id
        self.preview = preview
        self.page = 0
        self.pages = render.suspend_preview_pages(preview)
        if self.pages == 1:
            self.remove_item(self.prev_button)
            self.remove_item(self.next_button)
        self._update_buttons()

    def text(self) -> str:
        return render.suspend_preview_text(self.preview, self.page)

    def _update_buttons(self) -> None:
        self.prev_button.disabled = self.page == 0
        self.next_button.disabled = self.page >= self.pages - 1

    async def _show(self, interaction: discord.Interaction, page: int) -> None:
        self.page = min(max(page, 0), self.pages - 1)
        self._update_buttons()
        await interaction.response.edit_message(
            content=self.text(), view=self, allowed_mentions=adapter.NO_MENTIONS
        )

    @discord.ui.button(label="Suspend", style=discord.ButtonStyle.danger, row=0)
    async def suspend_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["SuspendConfirmView"]
    ) -> None:
        await interaction.response.defer()
        rng = self.preview.suspension
        async with adapter.uows(interaction)() as uow:
            out = await suspensions.suspend(
                uow, adapter.actor_from(interaction), self.todo_id, rng.start, rng.end
            )
        change = await adapter.apply(interaction, out)
        await interaction.edit_original_response(
            content=render.suspended_text(change),
            view=None,
            allowed_mentions=adapter.NO_MENTIONS,
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=0)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["SuspendConfirmView"]
    ) -> None:
        await interaction.response.edit_message(content="Not suspended.", view=None)
        self.stop()

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=1)
    async def prev_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["SuspendConfirmView"]
    ) -> None:
        await self._show(interaction, self.page - 1)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button["SuspendConfirmView"]
    ) -> None:
        await self._show(interaction, self.page + 1)
